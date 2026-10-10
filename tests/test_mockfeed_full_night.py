"""The Full-night fault script (#48; #17 § Rehearsal plan, Fault script).

Each data fault is served by the pure response function and run through the payload function with
the real Night Bundle, so every test asserts the reader state docs/full-night-faults.md lists.
"""

import json
from datetime import datetime
from itertools import pairwise
from pathlib import Path

import pytest

from election_night.alerts import count_decreases
from election_night.bundle import load_bundle
from election_night.feed import OFFICES
from election_night.mockfeed.feed import (
    COMPLETE_MINUTE,
    FULL_NIGHT,
    FULL_NIGHT_TAIL,
    HTTP_KINDS,
    NIGHT_START,
    MockFeed,
)
from election_night.mockfeed.scenario import load_scenario
from election_night.payload import build_payload
from election_night.pipeline import FILES

ROOT = Path(__file__).parent.parent
ALL, WARD = FILES
START = 1_800_000_000_000


def night(hhmm: str, day: int = 26) -> int:
    at = datetime.fromisoformat(f"2026-10-{day}T{hhmm}:00-04:00")
    return START + int(at.timestamp() * 1000) - NIGHT_START


def minute(m: float) -> int:
    """The wall-clock ms at night minute `m` after 19:50 (real time)."""
    return START + int(m * 60_000)


@pytest.fixture(scope="module")
def scenario():
    return load_scenario(seed=0)


@pytest.fixture(scope="module")
def feed(scenario):
    return MockFeed(scenario, start_ms=START, speed=1.0, faults=FULL_NIGHT, tail=FULL_NIGHT_TAIL)


@pytest.fixture(scope="module")
def clean(scenario):
    return MockFeed(scenario, start_ms=START, speed=1.0, faults=(), tail=FULL_NIGHT_TAIL)


@pytest.fixture(scope="module")
def bundle():
    return load_bundle(ROOT / "data" / "night-bundle" / "night-bundle.json")


def bodies(feed, now):
    responses = [feed.respond(f, now, None) for f in FILES]
    assert [r.status for r in responses] == [200, 200]
    return [r.body for r in responses]


def payload(feed, now, bundle):
    return json.loads(build_payload(*bodies(feed, now), bundle))


def race(p, rid):
    (r,) = [r for r in p["races"] if r["id"] == rid]
    return r


def votes(r) -> int:
    return sum(c["votes"] for c in r["candidates"])


def the(kind):
    (fault,) = [f for f in FULL_NIGHT if f.kind == kind]
    return fault


def mid(fault) -> int:
    return minute(fault.start + fault.minutes / 2)


# Per-race faults: (kind, race, the race's expected state, its Withdrawal or fault reason).
PER_RACE = [
    ("row-unreadable", "councillor-4", "no_figures", "row_unreadable"),
    ("race-missing", "tcdsb-3", "no_figures", "race_missing"),
    ("received-above-polls", "councillor-6", "counting", "polls_received_above_polls"),
    ("polls-zero", "tdsb-5", "counting", "polls_zero"),
    ("polls-differ", "councillor-7", "counting", "polls_differ_from_bundle"),
    ("votes-mismatch", "councillor-8", "counting", "votes_received_mismatch"),
    ("above-expected", "councillor-10", "counting", "count_above_expected"),
]


@pytest.mark.parametrize("kind, rid, state, reason", PER_RACE)
def test_each_per_race_fault_fails_its_race_closed(feed, bundle, kind, rid, state, reason):
    fault = the(kind)
    assert fault.race == rid
    p = payload(feed, mid(fault), bundle)
    r = race(p, rid)
    assert r["state"] == state
    if state == "no_figures":
        assert r["fault"] == {"reason": reason} and r["projection"] is None
    else:
        assert r["withdrawal"] == {"reason": reason} and r["projection"] is None
        assert r["candidates"][0]["votes"] > 0  # the tally is still shown
    if reason.startswith("polls"):
        assert r["progress"] is None  # Reporting Progress hidden
    # Per race, never per level: a neighbouring race of the same level is untouched.
    others = [x for x in p["races"] if x["level"] == r["level"] and x["id"] != rid]
    assert any(x["withdrawal"] is None and x["state"] == "counting" for x in others)


def test_an_unknown_name_shows_the_feed_name_and_count_only_continues(feed, bundle):
    fault = the("unknown-name")
    r = race(payload(feed, mid(fault), bundle), fault.race)
    assert "Rehearsal Unknown" in [c["key"] for c in r["candidates"]]
    assert r["withdrawal"] is None and r["state"] == "counting"
    assert r["projection"] is not None


def test_a_race_not_in_the_bundle_is_ignored(feed, bundle):
    fault = the("race-not-in-bundle")
    a = json.loads(bodies(feed, mid(fault))[0])
    rows = [row["num"] for o in a["office"] if o["id"] == 2 for row in o["ward"]]
    assert "26" in rows
    assert fault.race not in {r["id"] for r in payload(feed, mid(fault), bundle)["races"]}


def test_a_mayoral_ward_row_failure_withdraws_the_mayoral_projection(feed, bundle):
    fault = the("ward-votes-counted")
    p = payload(feed, mid(fault), bundle)
    assert race(p, "mayor")["withdrawal"] == {"reason": "ward_votes_counted_mismatch"}
    assert votes(race(p, "mayor")) > 0


def test_a_count_decrease_is_mirrored_and_recorded(feed, clean, bundle):
    fault = the("count-decrease")
    before = payload(feed, minute(fault.start) - 1, bundle)
    during = payload(feed, minute(fault.start), bundle)
    assert votes(race(during, fault.race)) < votes(race(before, fault.race))
    assert votes(race(during, fault.race)) < votes(
        race(payload(clean, minute(fault.start), bundle), fault.race)
    )
    decreases = count_decreases(before, during)
    assert [d["race"] for d in decreases if d["scope"] == "ward"] == [fault.race]


def test_the_per_race_faults_hit_distinct_races_in_one_window():
    per_race = [f for f in FULL_NIGHT if f.race and f.kind != "all-in"]
    assert len({f.race for f in per_race}) == len(per_race) == 11
    assert len({(f.start, f.minutes) for f in per_race}) == 1


def test_the_files_regenerated_as_zeros_mid_count(feed, bundle):
    fault = the("zeros")
    before = payload(feed, minute(fault.start) - 1, bundle)
    during = payload(feed, mid(fault), bundle)
    assert during["state"] == "results" and during["rehearsal"] is True
    assert all(votes(r) == 0 for r in during["races"] if r["state"] != "acclaimed")
    assert during["seq"]["all_office"] > before["seq"]["all_office"]  # a current seq
    citywide = [d for d in count_decreases(before, during) if d["scope"] == "citywide"]
    assert citywide  # the sounding count-decrease alert
    after = payload(feed, minute(fault.start + fault.minutes), bundle)
    assert votes(race(after, "mayor")) > votes(race(before, "mayor"))


def test_a_stalled_seq_serves_new_counts_under_a_frozen_seq(feed, bundle):
    fault = the("stalled-seq")
    first = payload(feed, minute(fault.start), bundle)
    later = payload(feed, minute(fault.start + fault.minutes - 1), bundle)
    assert first["seq"] == later["seq"]
    assert votes(race(later, "mayor")) > votes(race(first, "mayor"))
    a, w = first["seq"]["all_office"], first["seq"]["ward_by_ward"]
    assert len(feed.reference(a, w)) == fault.minutes
    after = payload(feed, minute(fault.start + fault.minutes), bundle)
    assert after["seq"]["all_office"] > a


def test_the_http_faults_all_run(feed):
    assert {f.kind for f in FULL_NIGHT if f.kind in HTTP_KINDS} == HTTP_KINDS
    assert feed.respond(ALL, mid(the("5xx")), None).status == 503


def test_file_level_faults_never_overlap():
    whole = [f for f in FULL_NIGHT if f.race is None]
    batch = [f for f in FULL_NIGHT if f.race and f.kind != "all-in"][:1]
    windows = sorted((f.start, f.start + f.minutes) for f in whole + batch)
    assert all(a[1] < b[0] for a, b in pairwise(windows))  # clean minutes between


def test_a_near_silent_two_hour_tail(feed, scenario):
    assert FULL_NIGHT_TAIL[0] > COMPLETE_MINUTE
    assert FULL_NIGHT_TAIL[-1] - COMPLETE_MINUTE == 120
    assert feed.step_at(minute(COMPLETE_MINUTE)) == scenario.steps - len(FULL_NIGHT_TAIL)
    first = feed.respond(ALL, minute(COMPLETE_MINUTE), None)
    # Between arrivals the files aren't regenerated.
    assert feed.respond(ALL, minute(FULL_NIGHT_TAIL[0]) - 1, first.headers["ETag"]).status == 304
    for k, arrival in enumerate(FULL_NIGHT_TAIL, start=1):
        assert feed.step_at(minute(arrival)) == scenario.steps - len(FULL_NIGHT_TAIL) + k
    last = feed.respond(ALL, minute(FULL_NIGHT_TAIL[-1]), None)
    assert feed.respond(ALL, night("09:00", day=27), last.headers["ETag"]).status == 304


def test_a_race_at_100_percent_while_its_votes_still_rise(feed, bundle, scenario):
    fault = the("all-in")
    last_ward = scenario.night.units[scenario.order[-1]].ward
    assert fault.race is None and feed.all_in_race == f"councillor-{last_ward}"
    early = race(payload(feed, minute(fault.start), bundle), feed.all_in_race)
    late = race(payload(feed, minute(fault.start + fault.minutes) - 1, bundle), feed.all_in_race)
    for r in (early, late):
        assert r["state"] == "all_units_in" and r["projection"] is None
        assert r["progress"]["received"] == r["progress"]["total"]
    final = race(payload(feed, minute(fault.start + fault.minutes), bundle), feed.all_in_race)
    assert votes(final) > votes(early)


def test_the_reference_is_what_was_served_faults_included(feed):
    for kind in ("row-unreadable", "above-expected", "count-decrease", "zeros"):
        fault = the(kind)
        a_body, w_body = bodies(feed, mid(fault))
        a, w = (json.loads(b) for b in (a_body, w_body))
        (ref,) = feed.reference(int(a["seq"]), int(w["seq"]))
        mayor = {c["name"]: int(c["votesReceived"]) for c in w["office"]["candidate"]}
        assert ref["mayor"] == mayor
        if fault.race:
            prefix, num = fault.race.split("-")
            (office,) = [k for k, (p, _) in OFFICES.items() if p == prefix]
            (row,) = [
                r for o in a["office"] if o["id"] == office for r in o["ward"] if r["num"] == num
            ]
            if kind == "row-unreadable":
                assert ref[fault.race] is None
            else:
                assert ref[fault.race] == {
                    c["name"]: int(c["votesReceived"]) for c in row["candidate"]
                }


def test_the_reference_before_the_start_is_the_zeroed_files(feed):
    a, w = (json.loads(b) for b in bodies(feed, START - 1))
    (ref,) = feed.reference(int(a["seq"]), int(w["seq"]))
    assert all(v == 0 for race in ref.values() for v in race.values())


def test_the_doc_lists_every_fault():
    doc = (ROOT / "docs" / "full-night-faults.md").read_text()
    for fault in FULL_NIGHT:
        assert f"`{fault.kind}`" in doc


def test_the_per_race_batch_ends_with_one_more_decrease(feed, bundle):
    """When the batch ends, the inflated race drops back to its real count: a second
    ward-scope decrease, listed in the doc."""
    end = minute(the("above-expected").start + the("above-expected").minutes)
    decreases = count_decreases(payload(feed, end - 1, bundle), payload(feed, end, bundle))
    assert [d["race"] for d in decreases] == ["councillor-10"]
