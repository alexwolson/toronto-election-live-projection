"""The `election-night` command."""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import redis

from election_night.bundle import OPENING_2026, build_bundle, load_bundle, write_bundle
from election_night.feed import check_status
from election_night.gates import s3_record
from election_night.goldens import write_goldens
from election_night.names import fetch_name_inputs, load_name_inputs
from election_night.payload import build_payload
from election_night.pipeline import FILES, Pipeline, Watchdog, run
from election_night.store import PIPELINES, Store

CITY_FEED = "https://mediaresults.toronto.ca/results"
# Defaults resolve against the repo root, wherever the command is run from.
ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "feed"
BUNDLE = ROOT / "data" / "night-bundle" / "night-bundle.json"
BACKEND_REPO = "alexwolson/toronto-election-poll-tracker-backend"
OUTCOMES_PATH = "data/raw/elections/mayoral_outcomes.csv"
NAME_INPUTS = ROOT / "data" / "night-bundle" / "inputs"


def fetch(url: str, cache: Path) -> bytes:
    """One conditional GET. The body and ETag are cached, and a 304 serves the cached body."""
    body_path, etag_path = cache.with_suffix(".json"), cache.with_suffix(".etag")
    request = urllib.request.Request(url, headers={"Accept-Encoding": "identity"})
    if body_path.exists() and etag_path.exists():
        request.add_header("If-None-Match", etag_path.read_text(encoding="utf-8").strip())
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            status, body, etag = response.status, response.read(), response.headers.get("ETag")
    except urllib.error.HTTPError as error:
        status, body, etag = error.code, b"", None
    print(f"{url}: {status}", file=sys.stderr)
    check_status(status)
    if status == 304:
        return body_path.read_bytes()
    cache.parent.mkdir(parents=True, exist_ok=True)
    body_path.write_bytes(body)
    if etag:
        etag_path.write_text(etag, encoding="utf-8")
    return body


def cmd_payload(args) -> None:
    bodies = [fetch(f"{args.base_url}/{name}", args.cache_dir / name) for name in FILES]
    body = build_payload(*bodies, load_bundle(args.bundle))
    if args.pretty:
        body = json.dumps(json.loads(body), ensure_ascii=False, indent=2).encode("utf-8")
    sys.stdout.buffer.write(body + b"\n")


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"{name} must be set")
    return value


def cmd_pipeline(args) -> None:
    # Only the feed base URL and the store credentials come from the environment.
    base_url, redis_url = _env("FEED_BASE_URL"), _env("REDIS_URL")
    client = redis.Redis.from_url(redis_url, socket_timeout=10, socket_connect_timeout=10)
    pipeline = Pipeline(args.name, base_url, load_bundle(args.bundle), Store(client))
    run(pipeline, args.stagger, Watchdog())


def cmd_bundle(args) -> None:
    city = args.fixtures / "city-2026"
    bundle = build_bundle(
        (city / FILES[0]).read_bytes(),
        (city / FILES[1]).read_bytes(),
        args.opening_time,
        names=load_name_inputs(args.names),
    )
    write_bundle(bundle, args.out)
    print(args.out)


def cmd_goldens(args) -> None:
    for path in write_goldens(args.fixtures, load_name_inputs(args.names), args.out):
        print(path)


def cmd_s3_shift(args) -> None:
    source = {"repo": BACKEND_REPO, "path": OUTCOMES_PATH, "commit": args.outcomes_commit}
    print(json.dumps(s3_record(args.forecasts, args.outcomes, source), indent=2, sort_keys=True))


def cmd_name_inputs(args) -> None:
    source = fetch_name_inputs(args.backend_release, args.out)
    print(json.dumps(source, indent=1))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="election-night")
    commands = parser.add_subparsers(required=True)

    payload = commands.add_parser("payload", help="fetch the City files once; print the payload")
    payload.add_argument("--base-url", default=CITY_FEED)
    payload.add_argument("--bundle", type=Path, default=BUNDLE)
    payload.add_argument("--cache-dir", type=Path, default=ROOT / ".cache" / "feed")
    payload.add_argument("--pretty", action="store_true")
    payload.set_defaults(run=cmd_payload)

    pipe = commands.add_parser(
        "pipeline", help="poll the City feed every 60 s; publish to the store"
    )
    pipe.add_argument("--name", choices=PIPELINES, required=True)
    pipe.add_argument("--stagger", type=float, default=0.0, help="seconds past each minute")
    pipe.add_argument("--bundle", type=Path, default=BUNDLE)
    pipe.set_defaults(run=cmd_pipeline)

    bundle = commands.add_parser(
        "bundle", help="build the Night Bundle from the City test files and the name inputs"
    )
    bundle.add_argument("--fixtures", type=Path, default=FIXTURES)
    bundle.add_argument("--names", type=Path, default=NAME_INPUTS)
    bundle.add_argument("--opening-time", default=OPENING_2026)
    bundle.add_argument("--out", type=Path, default=BUNDLE)
    bundle.set_defaults(run=cmd_bundle)

    golden = commands.add_parser("goldens", help="write the golden payloads")
    golden.add_argument("--fixtures", type=Path, default=FIXTURES)
    golden.add_argument("--names", type=Path, default=NAME_INPUTS)
    golden.add_argument("--out", type=Path, default=ROOT / "goldens" / "payload")
    golden.set_defaults(run=cmd_goldens)

    s3 = commands.add_parser(
        "s3-shift", help="print the stress-test shift block of the pre-registration (S3)"
    )
    s3.add_argument("--forecasts", type=Path, default=ROOT / "data" / "forecasts" / "holdout-1d")
    s3.add_argument(
        "--outcomes",
        type=Path,
        required=True,
        help=f"the Backend's {OUTCOMES_PATH}",
    )
    s3.add_argument(
        "--outcomes-commit", required=True, help="the Backend commit that last changed that file"
    )
    s3.set_defaults(run=cmd_s3_shift)

    inputs = commands.add_parser(
        "name-inputs",
        help="vendor the registry, and the forecast's ids and Results candidacies, for the bundle",
    )
    inputs.add_argument("--backend-release", required=True, help="the pinned forecast's release")
    inputs.add_argument("--out", type=Path, default=NAME_INPUTS)
    inputs.set_defaults(run=cmd_name_inputs)

    args = parser.parse_args(argv)
    args.run(args)
