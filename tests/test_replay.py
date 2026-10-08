"""The Replay generator, by round trip (spec #17 § Testing Decisions, seam 2; ticket #28).

The final snapshot of every Replay must equal the certified totals, every snapshot must read as the
City's two files do, and fixed seeds must give fixed orders.
"""

import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from election_night.feed import COUNCILLOR_OFFICE_ID
from election_night.gates import load_preregistration
from election_night.payload import build_payload
from election_night.replay.captures import real_captures
from election_night.replay.historical import YEARS, load_night
from election_night.replay.orders import arrival_order, orders
from election_night.replay.snapshots import night_bundle, snapshots

ROOT = Path(__file__).parent.parent
PREREG = load_preregistration(ROOT / "gates" / "preregistration.json")

# Research 03 § 2 (OBSERVED from the same workbooks): contests, candidacies and valid votes per
# office, and the night's units below 96 and from 96 up.
COVERAGE = {
    2014: {1: (1, 65, 981_054), 2: (44, 358, 931_336), 3: (22, 127, 661_731), 4: (12, 42, 172_323)},
    2018: {1: (1, 35, 755_493), 2: (25, 242, 749_427), 3: (22, 156, 534_447), 4: (12, 53, 126_296)},
    2022: {1: (1, 31, 551_890), 2: (25, 163, 539_312), 3: (22, 129, 393_430), 4: (12, 40, 90_584)},
    2023: {1: (1, 102, 724_638)},
}
UNITS = {2014: (1_679, 88), 2018: (1_700, 100), 2022: (1_460, 75), 2023: (1_351, 100)}


@pytest.fixture(scope="module")
def nights():
    return {year: load_night(year, PREREG) for year in YEARS}


def _races(all_office: bytes) -> dict[tuple[int, str], dict]:
    data = json.loads(all_office)
    return {(o["id"], w["num"]): w for o in data["office"] for w in o["ward"]}


def _votes(row: dict) -> dict[str, int]:
    return {c["name"]: int(c["votesReceived"]) for c in row["candidate"]}


def test_the_replayed_nights_are_the_pre_registered_ones():
    nights = PREREG["nights"]
    listed = {y for level in ("mayor", "council", "trustee") for y in nights[level]["years"]}
    assert sorted(listed) == list(YEARS)


@pytest.mark.parametrize("year", YEARS)
def test_the_loaders_reproduce_research_03s_coverage(nights, year):
    night = nights[year]
    regular = sum(1 for u in night.units if u.code < 96)
    assert (regular, len(night.units) - regular) == UNITS[year]
    for office_id, (contests, candidacies, valid) in COVERAGE[year].items():
        races = [r for r in night.races if r.office_id == office_id]
        assert len(races) == contests
        assert sum(len(r.candidates) for r in races) == candidacies
        assert sum(r.certified.sum() for r in races) == valid


@pytest.mark.parametrize("year", YEARS)
def test_ward_aggregates_are_the_pre_registered_codes_and_96_is_election_day(nights, year):
    codes = set(PREREG["arrival_orders"]["ward_aggregates"]["codes"])
    for unit in nights[year].units:
        assert unit.ward_aggregate == (unit.code in codes)


def test_2014_runs_on_its_44_wards(nights):
    assert len(nights[2014].wards) == 44
    assert sum(1 for r in nights[2014].races if r.office_id == COUNCILLOR_OFFICE_ID) == 44


KINDS = PREREG["arrival_orders"]["seeds"]["kinds"]


@pytest.mark.parametrize("year", YEARS)
@pytest.mark.parametrize("kind", KINDS)
def test_the_final_snapshot_equals_the_certified_totals(nights, year, kind):
    night = nights[year]
    order = arrival_order(night, PREREG, kind, 0)
    (final,) = snapshots(night, order, steps=[len(order)])

    rows = _races(final.all_office)
    for race in night.races:
        assert _votes(rows[(race.office_id, race.num)]) == dict(
            zip(race.candidates, race.certified.tolist())
        )
        row = rows[(race.office_id, race.num)]
        assert row["pollsReceived"] == row["polls"] == str(len(race.units))

    mayor = night.mayor
    office = json.loads(final.ward_by_ward)["office"]
    assert {c["name"]: int(c["votesReceived"]) for c in office["candidate"]} == dict(
        zip(mayor.candidates, mayor.certified.tolist())
    )
    assert office["pollsReceived"] == office["polls"] == str(len(night.units))


@pytest.mark.parametrize("year", YEARS)
@pytest.mark.parametrize("kind", KINDS)
def test_every_snapshot_reads_as_the_night_does(nights, year, kind):
    night = nights[year]
    bundle = night_bundle(night)
    order = arrival_order(night, PREREG, kind, 3)
    # Every step of one order of the smallest night; a spread of steps elsewhere, to keep the
    # suite quick.
    every = year == 2023 and kind == "late"
    steps = list(range(len(order) + 1)) if every else [*range(0, len(order), 97), len(order)]

    seen = []
    for snap in snapshots(night, order, steps=steps):
        payload = json.loads(build_payload(snap.all_office, snap.ward_by_ward, bundle))
        assert payload["state"] == "results"
        assert len(payload["races"]) == len(night.races)
        assert not [r["id"] for r in payload["races"] if r["state"] == "no_figures"]
        assert snap.all_office_seq != snap.ward_by_ward_seq
        seen.append(snap.step)
        received = {r["id"]: r["progress"]["received"] for r in payload["races"]}
        if snap.step == 0:
            assert set(received.values()) == {0}
        if snap.step == len(order):
            assert {r["state"] for r in payload["races"]} == {"all_units_in"}
        mayor = payload["races"][0]
        assert sum(w["progress"]["received"] for w in mayor["wards"]) == snap.step
    assert seen == steps


def test_snapshots_advance_one_unit_per_step(nights):
    night = nights[2023]
    order = arrival_order(night, PREREG, "late", 0)
    snaps = list(snapshots(night, order, steps=range(5)))
    received = [json.loads(s.ward_by_ward)["office"]["pollsReceived"] for s in snaps]
    assert received == ["0", "1", "2", "3", "4"]
    seqs = [s.all_office_seq for s in snaps]
    assert seqs == sorted(set(seqs))


def test_the_historical_night_bundle_holds_the_races_and_ballot_names(nights):
    night = nights[2022]
    bundle = night_bundle(night)
    assert bundle["opening_time"] == "2022-10-24T20:00:00-04:00"
    assert [r["id"] for r in bundle["races"]][:3] == ["mayor", "councillor-1", "councillor-2"]
    council_1 = bundle["races"][1]
    assert council_1["name"] == "Etobicoke North"
    assert council_1["polls"] == 55
    assert [c["key"] for c in council_1["candidates"]][:2] == ["Abbey Abraham", "Britton Bill"]
    assert len(bundle["races"][0]["wards"]) == 25


def _fingerprint(night, order) -> str:
    pairs = [(night.units[i].ward, night.units[i].code) for i in order]
    return hashlib.sha256(json.dumps(pairs).encode()).hexdigest()[:16]


def test_fixed_seeds_give_fixed_orders(nights):
    night = nights[2022]
    for kind in PREREG["arrival_orders"]["seeds"]["kinds"]:
        a = arrival_order(night, PREREG, kind, 7)
        assert np.array_equal(a, arrival_order(night, PREREG, kind, 7))
        assert not np.array_equal(a, arrival_order(night, PREREG, kind, 8))
        assert sorted(a.tolist()) == list(range(len(night.units)))


# The orders as first generated, pinned so no later change to the code or to numpy can move them
# after the first replay run.
PINNED = {
    "early": "8ae33cb8c18dc97b",
    "interleaved": "20c0168fe8210eff",
    "late": "f2f2f55d45190f83",
    "ward_clustered": "7abfa16dea16c4c5",
    "size_largest_first": "5b16203e6154a8e7",
    "size_smallest_first": "c19279b31006c674",
}


def test_the_orders_are_pinned(nights):
    night = nights[2022]
    emitted = {k: _fingerprint(night, arrival_order(night, PREREG, k, 0)) for k in PINNED}
    assert emitted == PINNED


def test_orders_are_read_from_the_preregistration_file(nights):
    night = nights[2022]
    other = copy.deepcopy(PREREG)
    other["arrival_orders"]["seeds"]["root"] += 1
    assert not np.array_equal(
        arrival_order(night, PREREG, "early", 0), arrival_order(night, other, "early", 0)
    )

    listed = orders(night, PREREG)
    per_kind = {}
    for kind, index, _ in listed:
        per_kind[kind] = per_kind.get(kind, 0) + 1
    assert per_kind == {
        "early": 20,
        "interleaved": 20,
        "late": 20,
        "ward_clustered": 20,
        "size_largest_first": 20,
        "size_smallest_first": 20,
    }


def _positions(night, order):
    aggregate = np.array([night.units[i].ward_aggregate for i in order])
    return np.flatnonzero(aggregate), np.flatnonzero(~aggregate)


@pytest.mark.parametrize("index", range(5))
def test_early_puts_every_ward_aggregate_first(nights, index):
    night = nights[2022]
    agg, ed = _positions(night, arrival_order(night, PREREG, "early", index))
    assert agg.max() < ed.min()


@pytest.mark.parametrize("index", range(5))
def test_late_puts_every_ward_aggregate_after_85_percent_of_election_day_units(nights, index):
    night = nights[2023]
    order = arrival_order(night, PREREG, "late", index)
    aggregate = np.array([night.units[i].ward_aggregate for i in order])
    ed_before = np.cumsum(~aggregate)[aggregate]  # election-day units ahead of each block
    assert ed_before.min() >= 0.85 * (~aggregate).sum()


def test_interleaved_spreads_ward_aggregates_through_the_night(nights):
    night = nights[2022]
    agg, ed = _positions(night, arrival_order(night, PREREG, "interleaved", 0))
    assert agg.min() < ed.max() * 0.2 and agg.max() > ed.max() * 0.8


@pytest.mark.parametrize("year", (2014, 2022))
def test_ward_clustered_keeps_each_wards_election_day_units_together(nights, year):
    night = nights[year]
    order = arrival_order(night, PREREG, "ward_clustered", 0)
    wards = [night.units[i].ward for i in order if not night.units[i].ward_aggregate]
    runs = [w for i, w in enumerate(wards) if i == 0 or wards[i - 1] != w]
    assert sorted(runs) == sorted(set(wards))
    assert runs != sorted(runs)


@pytest.mark.parametrize("kind", ("size_largest_first", "size_smallest_first"))
def test_size_orders_sort_election_day_units_by_mayoral_votes(nights, kind):
    night = nights[2018]
    mayor = night.mayor
    size = dict(zip(mayor.units, mayor.votes.sum(axis=1).tolist()))
    order = arrival_order(night, PREREG, kind, 0)
    sizes = [size[night.units[i].key] for i in order if not night.units[i].ward_aggregate]
    assert sizes == sorted(sizes, reverse=kind == "size_largest_first")


def test_the_real_captures_are_named_checkpoints_in_the_replays_names(nights):
    captures = real_captures(PREREG, ROOT, nights)
    assert [(c.night, c.time_edt) for c in captures] == [
        (2022, "2022-10-24T21:09"),
        (2022, "2022-10-24T21:46"),
        (2022, "2022-10-24T23:01"),
        (2022, "2022-10-24T23:55"),
        (2023, "2023-06-26T20:26"),
    ]
    for capture in captures:
        night = nights[capture.night]
        payload = json.loads(
            build_payload(capture.all_office, capture.ward_by_ward, night_bundle(night))
        )
        assert payload["seq"]["all_office"] != payload["seq"]["ward_by_ward"]
        bundle_names = {
            r["id"]: {c["key"] for c in r["candidates"]} for r in night_bundle(night)["races"]
        }
        levels = {"mayor"} if capture.night == 2023 else {"council", "trustee"}
        checked = [r for r in payload["races"] if r["level"] in levels]
        assert checked
        for race in checked:
            assert race["state"] in ("counting", "all_units_in"), race["id"]
            keys = {c["key"]: c["votes"] for c in race["candidates"]}
            assert bundle_names[race["id"]] <= set(keys)
            extra = {k: v for k, v in keys.items() if k not in bundle_names[race["id"]]}
            assert extra == ({"Cynthia Lai": 0} if race["id"] == "councillor-23" else {})

    bailao = json.loads(
        build_payload(
            captures[-1].all_office, captures[-1].ward_by_ward, night_bundle(nights[2023])
        )
    )["races"][0]
    assert [c["key"] for c in bailao["candidates"][:2]] == ["Bailão Ana", "Chow Olivia"]
    assert bailao["progress"] == {"received": 1221, "total": 1451}
