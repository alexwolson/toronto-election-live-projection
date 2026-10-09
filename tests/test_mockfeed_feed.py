"""The Mock Feed's pure response function (spec #17 § Testing Decisions, seam 5; ticket #37).

Each response is a pure function of the scenario, start time, speed, clock and request: the City's
two files on the night's clock, with ETag/304, separate `seq`s, candidates re-sorted by votes,
string values, scheduled HTTP faults and the REHEARSAL marker.
"""

import json
from datetime import datetime
from email.utils import parsedate_to_datetime
from itertools import pairwise
from pathlib import Path

import pytest

from election_night.bundle import load_bundle
from election_night.feed import (
    UnreadableFile,
    race_id,
    read_all_office,
    read_ward_by_ward,
)
from election_night.mockfeed.feed import FAULTS, NIGHT_START, MockFeed
from election_night.mockfeed.scenario import load_scenario
from election_night.payload import build_payload
from election_night.pipeline import FILES, HTTP_TIMEOUT

ROOT = Path(__file__).parent.parent
ALL, WARD = FILES
START = 1_800_000_000_000  # an arbitrary wall-clock start, epoch ms
OPENING = int(datetime.fromisoformat("2026-10-26T20:00:00-04:00").timestamp() * 1000)


def night(hhmm: str) -> int:
    """The wall-clock ms at which a real-time feed's night clock reads `hhmm` EDT on Oct 26."""
    at = datetime.fromisoformat(f"2026-10-26T{hhmm}:00-04:00")
    return START + int(at.timestamp() * 1000) - NIGHT_START


@pytest.fixture(scope="module")
def scenario():
    return load_scenario(seed=0)


@pytest.fixture(scope="module")
def feed(scenario):
    return MockFeed(scenario, start_ms=START, speed=1.0)


def body(feed, file, now):
    response = feed.respond(file, now, None)
    assert response.status == 200
    return response


def seq(response) -> int:
    return int(json.loads(response.body)["seq"])


def test_the_start_maps_to_1950_on_the_night(scenario):
    assert NIGHT_START == int(datetime.fromisoformat("2026-10-26T19:50:00-04:00").timestamp() * 1e3)
    fast = MockFeed(scenario, start_ms=START, speed=10.0)
    at_start = seq(body(fast, ALL, START))
    assert NIGHT_START <= at_start < NIGHT_START + 60_000
    # One wall minute at 10x is ten night minutes: 20:00.
    assert OPENING <= seq(body(fast, ALL, START + 60_000)) < OPENING + 60_000


def test_the_two_files_have_separate_seqs_on_the_same_generation(feed):
    now = night("20:15")
    a, w = seq(body(feed, ALL, now)), seq(body(feed, WARD, now))
    assert a != w and abs(a - w) < 1_000
    assert read_all_office(body(feed, ALL, now).body).seq == a


def test_etag_and_last_modified_and_304(feed):
    now = night("20:10")
    first = body(feed, ALL, now)
    etag = first.headers["ETag"]
    assert etag.startswith('"') and etag.endswith('"')
    modified = parsedate_to_datetime(first.headers["Last-Modified"]).timestamp()
    assert int(modified) == seq(first) // 1000
    again = feed.respond(ALL, now + 20_000, etag)  # same generation
    assert again.status == 304 and again.body == b""
    assert again.headers["ETag"] == etag
    later = feed.respond(ALL, now + 60_000, etag)  # the next generation
    assert later.status == 200 and later.headers["ETag"] != etag


def _rows(data: dict) -> list[list[dict]]:
    """Every candidate list in either file."""
    office = data["office"]
    if isinstance(office, dict):  # ward-by-ward
        return [office["candidate"]]
    return [ward["candidate"] for o in office for ward in o["ward"]]


def _leaves(value):
    if isinstance(value, dict):
        for v in value.values():
            yield from _leaves(v)
    elif isinstance(value, list):
        for v in value:
            yield from _leaves(v)
    else:
        yield value


@pytest.mark.parametrize("file", FILES)
def test_values_are_strings_and_candidates_are_sorted_by_votes(feed, file):
    data = json.loads(body(feed, file, night("20:15")).body)
    # Every value is a string, as the City writes them; only the office ids are numbers.
    office_ids = [o["id"] for o in data["office"]] if isinstance(data["office"], list) else []
    assert [v for v in _leaves(data) if not isinstance(v, str)] == office_ids
    assert isinstance(data["seq"], str)
    counting = 0
    for candidates in _rows(data):
        votes = [int(c["votesReceived"]) for c in candidates]
        assert votes == sorted(votes, reverse=True)
        counting += sum(votes) > 0
    assert counting  # some races are counting at 20:15


def test_the_tallies_are_the_true_count_at_the_feeds_step(feed, scenario):
    now = night("20:15")
    step = feed.step_at(now)
    assert 0 < step < scenario.steps
    truth = scenario.true_count(step)
    a = read_all_office(body(feed, ALL, now).body)
    for office_id, num in a.rows:
        tally = a.tally(office_id, num)
        expected = truth.races[race_id(office_id, num)]
        assert tally.votes == expected.votes
        assert tally.polls_received == expected.polls_received
    w = read_ward_by_ward(body(feed, WARD, now).body)
    assert {t.num: t.votes for t in w.wards()} == {t.num: t.votes for t in truth.wards}


def test_the_count_completes_and_generation_stops(feed, scenario):
    late, later = body(feed, ALL, night("23:59")), body(feed, ALL, night("23:59") + 3_600_000)
    assert feed.step_at(night("23:59")) == scenario.steps
    assert seq(late) == seq(later) and late.headers["ETag"] == later.headers["ETag"]


@pytest.mark.parametrize("file", FILES)
def test_every_file_is_marked_rehearsal(feed, file):
    for now in (START - 3_600_000, night("19:55"), night("21:00") - 1, night("23:59")):
        response = feed.respond(file, now, None)
        assert "REHEARSAL" in json.loads(response.body)["electionDesc"]


def test_before_the_start_it_serves_the_zeroed_test_files(feed):
    response = body(feed, ALL, START - 1)
    test_file = read_all_office((ROOT / "tests/fixtures/feed/city-2026" / ALL).read_bytes())
    assert seq(response) == test_file.seq
    assert all(int(c) == 0 for c in _counts(json.loads(response.body)))


def _counts(data: dict) -> list[str]:
    return [c["votesReceived"] for row in _rows(data) for c in row]


def test_the_sept_28_repeat_shows_live_looking_data_before_2000_then_zeros(feed):
    before = [body(feed, f, night("19:55")) for f in FILES]
    assert all(seq(r) < OPENING for r in before)
    assert all(sum(int(c) for c in _counts(json.loads(r.body))) > 0 for r in before)
    at_opening = [body(feed, f, night("20:00") + 5_000) for f in FILES]
    assert all(seq(r) >= OPENING for r in at_opening)
    assert all(int(c) == 0 for r in at_opening for c in _counts(json.loads(r.body)))
    # The night's bundle reads the repeat as "before results", and the REHEARSAL bar shows.
    bundle = load_bundle(ROOT / "data" / "night-bundle" / "night-bundle.json")
    payload = json.loads(build_payload(before[0].body, before[1].body, bundle))
    assert payload["state"] == "before_results" and payload["rehearsal"] is True


def _fault(kind: str):
    (fault,) = [f for f in FAULTS if f.kind == kind]
    return fault, night("19:50") + (fault.start + fault.minutes / 2) * 60_000


def test_a_long_304_run_freezes_the_generation(feed):
    fault, mid = _fault("stall")
    frozen = body(feed, ALL, night("19:50") + fault.start * 60_000)
    assert feed.respond(ALL, mid, frozen.headers["ETag"]).status == 304
    assert feed.respond(WARD, mid, body(feed, WARD, mid).headers["ETag"]).status == 304
    after = night("19:50") + (fault.start + fault.minutes) * 60_000
    assert feed.respond(ALL, after, frozen.headers["ETag"]).status == 200


@pytest.mark.parametrize("kind, status", [("5xx", 503), ("throttle", 403)])
def test_status_faults_fail_both_files(feed, kind, status):
    _, mid = _fault(kind)
    assert [feed.respond(f, mid, None).status for f in FILES] == [status, status]


def test_a_timeout_holds_the_response_past_the_pipelines_timeout(feed):
    _, mid = _fault("timeout")
    assert all(feed.respond(f, mid, None).delay > HTTP_TIMEOUT for f in FILES)
    assert feed.respond(ALL, night("20:10"), None).delay == 0


def test_a_truncated_body_is_unreadable(feed):
    _, mid = _fault("truncated")
    response = feed.respond(ALL, mid, None)
    assert response.status == 200
    with pytest.raises(UnreadableFile):
        read_all_office(response.body)
    read_ward_by_ward(body(feed, WARD, mid).body)


def test_a_renamed_key_is_unreadable(feed):
    _, mid = _fault("renamed")
    response = feed.respond(WARD, mid, None)
    assert response.status == 200
    with pytest.raises(UnreadableFile):
        read_ward_by_ward(response.body)
    read_all_office(body(feed, ALL, mid).body)


def test_one_file_fails_while_the_other_is_fine(feed):
    _, mid = _fault("one-file")
    assert feed.respond(WARD, mid, None).status == 503
    read_all_office(body(feed, ALL, mid).body)


def test_the_faults_never_overlap_and_can_be_switched_off(scenario):
    windows = sorted((f.start, f.start + f.minutes) for f in FAULTS)
    assert all(a[1] <= b[0] for a, b in pairwise(windows))
    quiet = MockFeed(scenario, start_ms=START, speed=1.0, faults=())
    for fault in FAULTS:
        mid = night("19:50") + (fault.start + fault.minutes / 2) * 60_000
        for f in FILES:
            response = quiet.respond(f, mid, None)
            assert response.status == 200 and response.delay == 0
            (read_all_office if f == ALL else read_ward_by_ward)(response.body)


def test_unknown_files_are_not_found(feed):
    assert feed.respond("other.json", night("20:10"), None).status == 404
