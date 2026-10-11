"""The Rehearsal pass checklist's archive checks: exact tallies and byte-identical archives (#42).

Payloads are built from the Mock Feed by the real payload function and archived under their real
keys, one directory per pipeline, as a downloaded bucket would be.
"""

import json
from pathlib import Path

import pytest

from election_night.archive import payload_key
from election_night.bundle import load_bundle
from election_night.mockfeed.feed import FAULTS, FULL_NIGHT, FULL_NIGHT_TAIL, MockFeed
from election_night.mockfeed.scenario import load_scenario
from election_night.payload import build_payload
from election_night.pipeline import FILES
from election_night.rehearsal_checks import check_archives

ROOT = Path(__file__).parent.parent
START = 1_800_000_000_000


def minute(m: float) -> int:
    return START + int(m * 60_000)


@pytest.fixture(scope="module")
def bundle():
    # Without projection inputs: the checks read only the tallies, and the draws are slow.
    found = load_bundle(ROOT / "data" / "night-bundle" / "night-bundle.json")
    return {k: v for k, v in found.items() if k != "projection"}


@pytest.fixture(scope="module")
def plumbing():
    return MockFeed(load_scenario(seed=0), start_ms=START, speed=10.0, faults=FAULTS, tail=())


@pytest.fixture(scope="module")
def full_night():
    return MockFeed(
        load_scenario(seed=0), start_ms=START, speed=1.0, faults=FULL_NIGHT, tail=FULL_NIGHT_TAIL
    )


def served(feed, now) -> tuple[bytes, bytes]:
    return tuple(feed.respond(f, now, None).body for f in FILES)


def archive(directory: Path, payloads: list[bytes]) -> Path:
    for body in payloads:
        path = directory / payload_key(body)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    return directory


def payloads_at(feed, bundle, nows) -> list[bytes]:
    return [build_payload(*served(feed, now), bundle) for now in nows]


# Night minutes 15, 25 and 40 at 10x: wall minutes 1.5, 2.5 and 4.
COUNTING = [minute(1.5), minute(2.5), minute(4.0)]


def test_two_pipelines_publishing_what_was_served_pass(tmp_path, plumbing, bundle):
    bodies = payloads_at(plumbing, bundle, COUNTING)
    report = check_archives(
        plumbing, [archive(tmp_path / "fly", bodies), archive(tmp_path / "do", bodies)]
    )
    assert report.failures == []
    assert report.tallies > 0
    assert report.shared == len(COUNTING)


def test_a_tally_that_differs_from_the_feed_fails(tmp_path, plumbing, bundle):
    (body,) = payloads_at(plumbing, bundle, COUNTING[:1])
    payload = json.loads(body)
    race = next(r for r in payload["races"] if r["id"] == "mayor")
    race["candidates"][0]["votes"] += 1
    report = check_archives(plumbing, [archive(tmp_path / "fly", [json.dumps(payload).encode()])])
    assert len(report.failures) == 1
    assert "mayor" in report.failures[0]


def test_one_seq_pair_with_two_bodies_fails(tmp_path, plumbing, bundle):
    (body,) = payloads_at(plumbing, bundle, COUNTING[:1])
    other = json.loads(body)
    other["generated_note"] = "different bytes, same pair"
    report = check_archives(
        plumbing,
        [archive(tmp_path / "fly", [body]), archive(tmp_path / "do", [json.dumps(other).encode()])],
    )
    assert any("differ" in f for f in report.failures)


def test_a_pair_the_feed_never_served_fails(tmp_path, plumbing, bundle):
    (body,) = payloads_at(plumbing, bundle, COUNTING[:1])
    payload = json.loads(body)
    payload["seq"]["all_office"] += 1
    report = check_archives(plumbing, [archive(tmp_path / "fly", [json.dumps(payload).encode()])])
    assert any("never served" in f for f in report.failures)


def test_the_stalled_seq_may_differ_between_pipelines(tmp_path, full_night, bundle):
    # 21:20-21:30: new counts under one frozen pair, so each pipeline may archive its own.
    first, later = payloads_at(full_night, bundle, [minute(91), minute(95)])
    assert json.loads(first)["seq"] == json.loads(later)["seq"]
    assert first != later
    report = check_archives(
        full_night, [archive(tmp_path / "fly", [first]), archive(tmp_path / "do", [later])]
    )
    assert report.failures == []


def test_an_archive_with_no_payloads_fails(tmp_path, plumbing, bundle):
    bodies = payloads_at(plumbing, bundle, COUNTING[:1])
    (tmp_path / "do").mkdir()
    report = check_archives(plumbing, [archive(tmp_path / "fly", bodies), tmp_path / "do"])
    assert any("no payloads" in f for f in report.failures)
