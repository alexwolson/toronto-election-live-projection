"""The `election-night` command."""

import argparse
import json
import os
import signal
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import boto3
import redis
from botocore.config import Config

from election_night.alerts import Alerts
from election_night.archive import Archive, ArchiveWriter
from election_night.bundle import (
    OPENING_2026,
    PARAMS,
    build_night_bundle,
    load_bundle,
    night_params,
    write_bundle,
)
from election_night.feed import check_status
from election_night.freeze_gate import FRONTEND_REPO, check_archives
from election_night.gates import HOLDOUT_FORECASTS, load_preregistration, s3_record
from election_night.goldens import write_goldens
from election_night.mockfeed.feed import SCRIPTS, MockFeed
from election_night.mockfeed.scenario import load_scenario
from election_night.mockfeed.server import serve
from election_night.name_inputs import fetch_name_inputs, load_name_inputs, refresh_forecast
from election_night.payload import build_payload
from election_night.pipeline import FILES, Pipeline, Watchdog, now_ms, run
from election_night.projection.forecast_weighted import resolve_forecast
from election_night.replay.gate_result import write_gate_result
from election_night.replay.run import LEVELS, PREREGISTRATION, run_replay
from election_night.status import read_status, render_status
from election_night.store import PIPELINES, Store
from election_night.switches import SWITCHES, VALUES, flip, switch_key

CITY_FEED = "https://mediaresults.toronto.ca/results"
# Defaults resolve against the repo root, wherever the command is run from.
ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "feed"
BUNDLE = ROOT / "data" / "night-bundle" / "night-bundle.json"
BACKEND_REPO = "alexwolson/toronto-election-poll-tracker-backend"
OUTCOMES_PATH = "data/raw/elections/mayoral_outcomes.csv"
NAME_INPUTS = ROOT / "data" / "night-bundle" / "inputs"
ADVANCE = "advance_turnout_2026.json"  # the City's 2026 advance figure, beside the name inputs
# Each 2026 trustee area's City wards, from the City's school-board ward reference chart.
TRUSTEE_WARDS = ROOT / "data" / "mock-feed" / "trustee_wards_2026.csv"


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


def _night_bundle(path: Path) -> dict:
    """The Night Bundle with its pinned forecast resolved once, as at pipeline start: the draws
    sit beside the bundle. A missing, corrupt or unmatched forecast turns the mayor's variant
    off for the night, and is reported here, never failing the start."""
    bundle = resolve_forecast(load_bundle(path), path.parent)
    if "forecast_off" in bundle:
        print(f"mayor's forecast-weighted variant off: {bundle['forecast_off']}", file=sys.stderr)
    return bundle


def cmd_payload(args) -> None:
    bodies = [fetch(f"{args.base_url}/{name}", args.cache_dir / name) for name in FILES]
    body = build_payload(*bodies, _night_bundle(args.bundle))
    if args.pretty:
        body = json.dumps(json.loads(body), ensure_ascii=False, indent=2).encode("utf-8")
    sys.stdout.buffer.write(body + b"\n")


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"{name} must be set")
    return value


def cmd_pipeline(args) -> None:
    # URLs, buckets and credentials come from the environment (docs/store.md). The archive's
    # endpoint and keys are boto3's own: AWS_ENDPOINT_URL_S3, AWS_ACCESS_KEY_ID and so on.
    base_url, redis_url = _env("FEED_BASE_URL"), _env("REDIS_URL")
    alerts = Alerts(
        pipeline=_env("PING_URL_PIPELINE"),
        reader_path=_env("PING_URL_READER_PATH"),
        count_decrease=_env("PING_URL_COUNT_DECREASE"),
        reader_path_url=_env("READER_PATH_URL"),
    )
    s3 = boto3.client(
        "s3", config=Config(connect_timeout=10, read_timeout=20, retries={"max_attempts": 3})
    )
    archive = ArchiveWriter(Archive(s3, _env("ARCHIVE_BUCKET"), _env("ARCHIVE_PREFIX")))
    client = redis.Redis.from_url(redis_url, socket_timeout=10, socket_connect_timeout=10)
    pipeline = Pipeline(
        args.name,
        base_url,
        _night_bundle(args.bundle),
        Store(client),
        archive=archive,
        alerts=alerts,
    )
    run(pipeline, args.stagger, Watchdog())


def cmd_status(args) -> None:
    client = redis.Redis.from_url(_env("REDIS_URL"), socket_timeout=10, socket_connect_timeout=10)
    sys.stdout.write(render_status(read_status(client), now_ms()))


def cmd_switch(args) -> None:
    client = redis.Redis.from_url(_env("REDIS_URL"), socket_timeout=10, socket_connect_timeout=10)
    state = flip(client, args.switch, args.state)
    print(f"`{switch_key(args.switch)}` set to `{args.state}`; read back: **{state}**.")
    if state != args.state:
        sys.exit(f"{switch_key(args.switch)} reads back {state!r}, not {args.state!r}")


def cmd_bundle(args) -> None:
    bundle = build_night_bundle(
        args.fixtures / "city-2026",
        load_name_inputs(args.names),
        args.opening_time,
        TRUSTEE_WARDS,
        ROOT / "gates",
        args.names / ADVANCE,
        bundle_dir=args.out.parent,
        forecast_only=args.forecast_only,
    )
    write_bundle(bundle, args.out)
    print(args.out)


def cmd_params(args) -> None:
    path = ROOT / "gates" / PARAMS
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(night_params(ROOT / "gates"), indent=1, sort_keys=True)
    path.write_text(body + "\n", encoding="utf-8")
    print(path)


def cmd_goldens(args) -> None:
    for path in write_goldens(args.fixtures, load_name_inputs(args.names), args.out):
        print(path)


def cmd_s3_shift(args) -> None:
    source = {"repo": BACKEND_REPO, "path": OUTCOMES_PATH, "commit": args.outcomes_commit}
    print(json.dumps(s3_record(args.forecasts, args.outcomes, source), indent=2, sort_keys=True))


def cmd_name_inputs(args) -> None:
    fetch = refresh_forecast if args.forecast_only else fetch_name_inputs
    source = fetch(args.backend_release, args.out)
    print(json.dumps(source, indent=1))


def cmd_mock_feed(args) -> None:
    start = datetime.fromisoformat(args.start)
    if start.tzinfo is None:
        sys.exit("--start needs a UTC offset, e.g. 2026-10-15T19:00:00-04:00")
    if args.faults not in SCRIPTS:  # an env default skips argparse's choices
        sys.exit(f"MOCK_FEED_FAULTS must be one of {', '.join(sorted(SCRIPTS))}")
    faults, tail = SCRIPTS[args.faults]
    feed = MockFeed(
        load_scenario(args.seed),
        start_ms=int(start.timestamp() * 1000),
        speed=args.speed,
        faults=faults,
        tail=tail,
    )
    serve(feed, args.port)


def cmd_freeze_gate(args) -> None:
    count, failures = check_archives(
        args.archive, args.frontend_repo, args.frontend_commit, args.backend_release_tag
    )
    for failure in failures:
        print(f"FAIL {failure}")
    if failures:
        sys.exit(f"freeze gate failed: {len(failures)} failures in {count} payloads")
    print(
        f"freeze gate: {count} payloads pass at {args.frontend_commit}, {args.backend_release_tag}"
    )


def _timed_out(signum, frame):
    raise TimeoutError


def cmd_replay(args) -> None:
    prereg = load_preregistration(PREREGISTRATION)
    years = prereg["nights"][LEVELS[args.level].name]["years"]
    if args.nights and not args.smoke:
        sys.exit("--nights is for smoke runs: a Gate Result covers every pre-registered night")
    if not args.smoke and args.timeout is None:
        sys.exit("a full run needs --timeout, its hard timeout in seconds")
    if args.nights:
        years = args.nights
    elif args.smoke:
        years = years[-1:]  # the latest night, which holds the real captures
    out = args.out or ROOT / (".cache/gates-smoke" if args.smoke else "gates/results")
    # One thread per worker process: the pool's children inherit these before importing numpy.
    for name in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "MKL_NUM_THREADS",
    ):
        os.environ.setdefault(name, "1")
    started = time.monotonic()

    def heartbeat(done: int, total: int) -> None:
        elapsed = round(time.monotonic() - started, 1)
        line = {"level": args.level, "orders_done": done, "orders": total, "elapsed_s": elapsed}
        print(json.dumps(line), file=sys.stderr, flush=True)

    timeout = args.timeout if args.timeout is not None else 600
    signal.signal(signal.SIGALRM, _timed_out)
    signal.alarm(timeout)
    try:
        result, timing = run_replay(
            args.level, prereg, years, args.smoke, workers=args.workers, on_order=heartbeat
        )
    except TimeoutError:
        sys.exit(f"replay timed out after {timeout} s; no Gate Result written")
    finally:
        signal.alarm(0)
    path = write_gate_result(result, out, args.level)
    summary = {
        "gate_result": str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path),
        "pass": result["pass"],
        "criteria": result["criteria"],
        "cases": result["cases"],
        "timing": {k: round(v, 1) for k, v in timing.items()},
    }
    print(json.dumps(summary, indent=1))


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

    status = commands.add_parser(
        "status", help="print night status from the store at REDIS_URL, as Markdown; read-only"
    )
    status.set_defaults(run=cmd_status)

    switch = commands.add_parser(
        "switch", help="flip one switch in the store at REDIS_URL and read it back (#49)"
    )
    switch.add_argument("switch", choices=SWITCHES)
    switch.add_argument("state", choices=VALUES)
    switch.set_defaults(run=cmd_switch)

    bundle = commands.add_parser(
        "bundle", help="build the Night Bundle from the City test files and the name inputs"
    )
    bundle.add_argument("--fixtures", type=Path, default=FIXTURES)
    bundle.add_argument("--names", type=Path, default=NAME_INPUTS)
    bundle.add_argument("--opening-time", default=OPENING_2026)
    bundle.add_argument("--out", type=Path, default=BUNDLE)
    bundle.add_argument(
        "--forecast-only",
        action="store_true",
        help="the forecast-only rebuild: an unmatched forecast turns the variant off",
    )
    bundle.set_defaults(run=cmd_bundle)

    params = commands.add_parser(
        "params", help="fit the night's parameters on every historical night, into gates/params"
    )
    params.set_defaults(run=cmd_params)

    golden = commands.add_parser("goldens", help="write the golden payloads")
    golden.add_argument("--fixtures", type=Path, default=FIXTURES)
    golden.add_argument("--names", type=Path, default=NAME_INPUTS)
    golden.add_argument("--out", type=Path, default=ROOT / "goldens" / "payload")
    golden.set_defaults(run=cmd_goldens)

    s3 = commands.add_parser(
        "s3-shift", help="print the stress-test shift block of the pre-registration (S3)"
    )
    s3.add_argument("--forecasts", type=Path, default=HOLDOUT_FORECASTS)
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
    inputs.add_argument(
        "--forecast-only",
        action="store_true",
        help="refresh only the forecast; names are never refreshed by a forecast-only release",
    )
    inputs.add_argument("--out", type=Path, default=NAME_INPUTS)
    inputs.set_defaults(run=cmd_name_inputs)

    replay = commands.add_parser(
        "replay", help="score the Replays for one level and write its Gate Result"
    )
    replay.add_argument("--level", choices=LEVELS, required=True)
    replay.add_argument(
        "--smoke",
        action="store_true",
        help="the latest night, one order per timing pattern; written to .cache/gates-smoke",
    )
    replay.add_argument("--nights", type=int, nargs="+", help="the smoke run's nights")
    replay.add_argument(
        "--timeout",
        type=int,
        help="hard timeout in seconds (smoke default 600; required for a full run)",
    )
    replay.add_argument("--out", type=Path, help="where to write the Gate Result")
    replay.add_argument(
        "--workers", type=int, default=1, help="processes to replay orders on (default 1)"
    )
    replay.set_defaults(run=cmd_replay)

    mock = commands.add_parser(
        "mock-feed",
        help="serve the Mock Feed for a Rehearsal: the start maps to 19:50 EDT on Oct 26",
    )
    mock.add_argument(
        "--start",
        default=os.environ.get("MOCK_FEED_START"),
        required="MOCK_FEED_START" not in os.environ,
        help="the Rehearsal's start, ISO 8601 with an offset (env MOCK_FEED_START)",
    )
    mock.add_argument(
        "--speed",
        type=float,
        default=os.environ.get("MOCK_FEED_SPEED", "1"),  # converted only for mock-feed
        help="night minutes per wall minute: about 10 for Plumbing, 4 for the Dress "
        "(env MOCK_FEED_SPEED, default 1)",
    )
    mock.add_argument("--seed", type=int, default=0, help="the scenario's arrival order")
    mock.add_argument(
        "--faults",
        choices=sorted(SCRIPTS),
        default=os.environ.get("MOCK_FEED_FAULTS", "on"),
        help="the fault script: on (Plumbing's HTTP faults), full-night (#48's, with the tail; "
        "docs/full-night-faults.md) or off (env MOCK_FEED_FAULTS, default on)",
    )
    mock.add_argument("--port", type=int, default=os.environ.get("PORT", "8080"))
    mock.set_defaults(run=cmd_mock_feed)

    freeze = commands.add_parser(
        "freeze-gate",
        help="check archived payloads against one Frontend commit's validator and release tag",
    )
    freeze.add_argument(
        "--archive",
        type=Path,
        action="append",
        required=True,
        help="a local copy of an archive bucket; repeat for each pipeline's",
    )
    freeze.add_argument("--frontend-commit", required=True, help="the production build's full SHA")
    freeze.add_argument(
        "--backend-release-tag",
        required=True,
        help="the production BACKEND_RELEASE_TAG, as given to `npm run deploy:production`",
    )
    freeze.add_argument("--frontend-repo", default=FRONTEND_REPO, help="a local repo, in tests")
    freeze.set_defaults(run=cmd_freeze_gate)

    args = parser.parse_args(argv)
    args.run(args)
