#!/usr/bin/env python3
"""Low-rate collapse check for the preview's /live/results.json (#42, #17 § Rehearsal plan).

Sends about RATE GET requests per second for DURATION seconds, each with the
`x-vercel-protection-bypass` header read from an environment variable (its value is never
printed), and tallies status codes and `x-vercel-cache` values per second.

PASS on cache values: every response is a 200 whose `x-vercel-cache` is HIT or STALE (plus
anything given with --allow). Any BYPASS, missing header, other value, non-200 or request
error is a FAIL.

The second half of the pass rule, "function invocations stay about 4 per minute per region",
is not visible from here: read it in Vercel (docs/rehearsal-checklist.md § Plumbing).

Stdlib only. Usage:
  export VERCEL_AUTOMATION_BYPASS_SECRET=...   # never echo it
  ./collapse_check.py https://<preview>/live/results.json --rate 20 --duration 180
"""

import argparse
import collections
import concurrent.futures
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

MAX_RATE = 30  # a collapse check, not a load test (Vercel allows load tests on Enterprise only)
MAX_DURATION = 900
TIMEOUT = 15


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("url", help="the preview deployment's /live/results.json")
    p.add_argument("--rate", type=float, default=20.0, help="requests per second (default 20)")
    p.add_argument("--duration", type=float, default=180.0, help="seconds (default 180)")
    p.add_argument(
        "--secret-env",
        default="VERCEL_AUTOMATION_BYPASS_SECRET",
        help="NAME of the env var holding the bypass secret (default VERCEL_AUTOMATION_BYPASS_SECRET)",
    )
    p.add_argument(
        "--allow",
        default="",
        help="extra x-vercel-cache values that still pass, comma-separated (e.g. PRERENDER)",
    )
    p.add_argument("--json-out", help="also write the per-second tallies to this JSON file")
    a = p.parse_args(argv)
    if not 0 < a.rate <= MAX_RATE:
        p.error(f"--rate must be in (0, {MAX_RATE}]")
    if not 0 < a.duration <= MAX_DURATION:
        p.error(f"--duration must be in (0, {MAX_DURATION}]")
    parts = urllib.parse.urlsplit(a.url)
    local = parts.hostname in ("localhost", "127.0.0.1", "::1")
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        p.error(
            "the URL must be https (plain http only for localhost), so the secret isn't sent in clear"
        )
    return a


def fetch(url: str, secret: str) -> tuple[str, str]:
    """One GET; returns (status, cache) as strings. Never includes the secret in its result."""
    req = urllib.request.Request(
        url,
        headers={
            "x-vercel-protection-bypass": secret,
            "Accept-Encoding": "identity",
            "User-Agent": "collapse-check/1 (#42)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            r.read()
            return str(r.status), r.headers.get("x-vercel-cache") or "(none)"
    except urllib.error.HTTPError as e:
        return str(e.code), e.headers.get("x-vercel-cache") or "(none)"
    except Exception as e:  # noqa: BLE001 - tallied, not raised
        return f"error:{type(e).__name__}", "(none)"


def main(argv=None) -> int:
    a = parse_args(argv)
    secret = os.environ.get(a.secret_env)
    if not secret:
        print(f"env var {a.secret_env} is empty or unset; refusing to run", file=sys.stderr)
        return 2
    allowed = {"HIT", "STALE"} | {v.strip().upper() for v in a.allow.split(",") if v.strip()}

    per_sec: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
    lock = threading.Lock()
    total = int(a.rate * a.duration)
    interval = 1.0 / a.rate
    workers = max(8, int(a.rate * 2))

    def one(i: int, t0: float) -> None:
        status, cache = fetch(a.url, secret)
        with lock:
            c = per_sec[i]
            c[f"status={status}"] += 1
            c[f"cache={cache}"] += 1

    print(
        f"collapse check: {a.url}  rate={a.rate}/s  duration={a.duration}s  "
        f"requests={total}  bypass secret from ${a.secret_env} (not shown)",
        flush=True,
    )
    start = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for n in range(total):
            due = start + n * interval
            delay = due - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            pool.submit(one, int(n * interval), start)
    elapsed = time.monotonic() - start

    overall = collections.Counter()
    print("\nsecond  n   statuses                 x-vercel-cache")
    for s in sorted(per_sec):
        c = per_sec[s]
        overall.update(c)
        n = sum(v for k, v in c.items() if k.startswith("status="))
        st = " ".join(f"{k[7:]}:{v}" for k, v in sorted(c.items()) if k.startswith("status="))
        ca = " ".join(f"{k[6:]}:{v}" for k, v in sorted(c.items()) if k.startswith("cache="))
        print(f"{s:6d} {n:3d}   {st:24s} {ca}")

    statuses = {k[7:]: v for k, v in overall.items() if k.startswith("status=")}
    caches = {k[6:]: v for k, v in overall.items() if k.startswith("cache=")}
    sent = sum(statuses.values())
    print(f"\ntotal {sent} responses in {elapsed:.1f}s ({sent / elapsed:.1f}/s)")
    print("statuses:", json.dumps(statuses, sort_keys=True))
    print("x-vercel-cache:", json.dumps(caches, sort_keys=True))

    reasons = []
    if caches.get("BYPASS"):
        reasons.append(f"{caches['BYPASS']} BYPASS")
    bad_cache = {k: v for k, v in caches.items() if k not in allowed and k != "BYPASS"}
    if bad_cache:
        reasons.append(f"cache values outside {sorted(allowed)}: {bad_cache}")
    bad_status = {k: v for k, v in statuses.items() if k != "200"}
    if bad_status:
        reasons.append(f"non-200 responses: {bad_status}")
    if a.json_out:
        with open(a.json_out, "w") as f:
            json.dump(
                {
                    "url": a.url,
                    "rate": a.rate,
                    "duration": a.duration,
                    "per_second": {s: dict(c) for s, c in sorted(per_sec.items())},
                    "statuses": statuses,
                    "caches": caches,
                    "fail_reasons": reasons,
                },
                f,
                indent=1,
            )
    if reasons:
        print("RESULT: FAIL (cache values) -", "; ".join(reasons))
        return 1
    print(
        "RESULT: PASS (cache values: only " + "/".join(sorted(allowed)) + ", all 200). "
        "Now check function invocations in Vercel: ~4/min/region."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
