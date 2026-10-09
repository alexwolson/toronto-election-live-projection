"""The count-extension projection for single-unit races: council and trustee (#33)."""

import dataclasses
import json

import numpy as np
import pytest

from election_night.gates import load_preregistration
from election_night.payload import build_payload, project
from election_night.projection.count_extension import (
    Aggregate,
    Params,
    RaceInputs,
    WardInputs,
    aggregate_posterior,
    bands,
    draw_final_shares,
)
from election_night.projection.history import fold_projection, replay_bundle
from election_night.replay.historical import YEARS, load_night
from election_night.replay.orders import arrival_order
from election_night.replay.run import PREREGISTRATION
from election_night.replay.snapshots import night_bundle, snapshots

PARAMS = Params(kappa=50.0, size_cv=0.3, omega=30.0)


def one_ward(units: int = 10, base: float = 30_000.0, spread: float = 0.05) -> RaceInputs:
    """One City ward: `units` election-day units and three advance aggregates of known size."""
    aggregates = (
        Aggregate(code=97, votes=1_000.0, share=None, spread=spread),
        Aggregate(code=98, votes=3_000.0, share=None, spread=spread),
        Aggregate(code=99, votes=2_000.0, share=None, spread=spread),
    )
    return RaceInputs((WardInputs("1", base, units, aggregates),))


def test_the_enumeration_finds_which_aggregates_are_in():
    # Two units in, 3,500 votes counted. Expected totals put an election-day unit at 0-600
    # votes, so only "98 plus one election-day unit" fits the race's own count.
    posterior = aggregate_posterior(one_ward(base=20_000.0), PARAMS, received=2, counted=3_500)
    assert sum(posterior.values()) == pytest.approx(1.0)
    assert posterior[((97, 0), (98, 1), (99, 0))] > 0.9


def test_impossible_combinations_get_no_weight():
    # One unit in: at most one aggregate can be in.
    posterior = aggregate_posterior(one_ward(), PARAMS, received=1, counted=3_000)
    assert all(sum(n for _, n in inside) <= 1 for inside, p in posterior.items() if p > 0)


VOTES = np.array([300, 200, 100, 0])


def draws(received: int, votes=VOTES, inputs=None, params=PARAMS, seed=7):
    rng = np.random.default_rng(seed)
    return draw_final_shares(inputs or one_ward(), params, votes, received, rng)


def test_nothing_in_and_everything_in_have_no_projection():
    assert draws(0, votes=np.zeros(4, dtype=int)) is None
    assert draws(13) is None  # 10 election-day units and 3 aggregates: all in


def test_draws_are_final_shares_and_deterministic():
    first = draws(3)
    assert first.shape == (10_000, 4)
    assert np.allclose(first.sum(axis=1), 100.0)
    assert (first >= 0).all()
    assert np.array_equal(first, draws(3))


def test_a_candidate_with_no_votes_yet_can_still_gain():
    assert draws(3)[:, 3].max() > 0


def test_bands_are_ordered_and_narrow_as_units_arrive():
    keys = ("a", "b", "c", "d")
    early = bands(draws(2, votes=VOTES), keys)
    late = bands(draws(11, votes=VOTES * 6), keys)
    for key in keys:
        for band in (early, late):
            assert 0 <= band[key]["low"] <= band[key]["mid"] <= band[key]["high"] <= 100
    width = {name: b["a"]["high"] - b["a"]["low"] for name, b in (("early", early), ("late", late))}
    assert width["late"] < width["early"]


def test_one_identical_unit_left_barely_moves_the_shares():
    # Nine of ten election-day units and every aggregate in; unit shares tightly concentrated.
    tight = Params(kappa=1e6, size_cv=0.01, omega=1e6)
    votes = np.array([6_000, 3_000, 1_000])
    final = draws(12, votes=votes, params=tight)
    assert np.abs(final - 100 * votes / votes.sum()).max() < 0.5


# Per-fold fitting on the real historical files (ADR 0029).

PREREG = load_preregistration(PREREGISTRATION)


@pytest.fixture(scope="module")
def nights():
    return {year: load_night(year, PREREG) for year in YEARS}


def poisoned(night):
    """The same night with every vote changed: only its structure and electors survive."""
    races = tuple(
        dataclasses.replace(r, votes=r.votes[:, ::-1] * 3 + 1, certified=r.certified[::-1] * 3)
        for r in night.races
    )
    return dataclasses.replace(night, races=races)


@pytest.mark.parametrize("year", [2014, 2018, 2022])
def test_a_fold_never_sees_its_held_out_nights_votes(nights, year):
    clean = fold_projection(nights[year], nights, PREREG)
    dirty = fold_projection(
        poisoned(nights[year]), {**nights, year: poisoned(nights[year])}, PREREG
    )
    assert clean == dirty


def test_each_fold_fits_its_own_parameters(nights):
    params = {y: fold_projection(nights[y], nights, PREREG)["params"] for y in (2014, 2018, 2022)}
    assert params[2014] != params[2018] != params[2022]
    for fold in params.values():
        for level in ("council", "trustee"):
            assert set(fold[level]) == {"kappa", "size_cv", "omega"}
            assert all(v > 0 for v in fold[level].values())


def test_every_council_and_trustee_race_gets_inputs_that_cover_its_units(nights):
    night = nights[2022]
    fold = fold_projection(night, nights, PREREG)
    races = {(r.office_id, r.num): r for r in night.races}
    for spec in night_bundle(night)["races"]:
        if spec["level"] == "mayor":
            assert spec["id"] not in fold["races"]
            continue
        expected = fold["races"][spec["id"]]
        units = sum(w["election_day_units"] + len(w["aggregates"]) for w in expected["wards"])
        assert units == len(races[(spec["office_id"], spec["num"])].units) == spec["polls"]
        assert all(w["base"] > 0 for w in expected["wards"])


# The payload function, on a Replay of 2022 (the seam the night and the Replays share).


@pytest.fixture(scope="module")
def replay_2022(nights):
    night = nights[2022]
    bundle = replay_bundle(night, nights, PREREG)
    order = arrival_order(night, PREREG, "interleaved", 0)
    (snap,) = snapshots(night, order, steps=[len(order) // 2])
    return snap, bundle


def test_counting_council_and_trustee_races_carry_the_models_bands(replay_2022):
    snap, bundle = replay_2022
    body, draws = project(snap.all_office, snap.ward_by_ward, bundle)
    projected = [r for r in body["races"] if r["level"] in ("council", "trustee")]
    assert projected and all(r["state"] == "counting" for r in projected)
    for race in projected:
        keys = [c["key"] for c in race["candidates"]]
        assert race["projection"]["stub"] is False
        assert list(race["projection"]["bands"]) == ["count_only"]
        assert list(race["projection"]["bands"]["count_only"]) == keys
        assert draws[race["id"]]["count_only"][1].shape == (10_000, len(keys))
    mayor = next(r for r in body["races"] if r["id"] == "mayor")
    assert mayor["projection"]["stub"] is True  # #36


def test_the_payload_with_projections_is_deterministic(replay_2022):
    snap, bundle = replay_2022
    first = build_payload(snap.all_office, snap.ward_by_ward, bundle)
    assert first == build_payload(snap.all_office, snap.ward_by_ward, bundle)


def test_inputs_that_dont_match_the_races_units_fail_closed_to_the_count(replay_2022):
    snap, bundle = replay_2022
    broken = json.loads(json.dumps(bundle))
    race = next(r for r in broken["races"] if r["id"] == "councillor-1")
    race["expected"]["wards"][0]["election_day_units"] += 1
    body, draws = project(snap.all_office, snap.ward_by_ward, broken)
    row = next(r for r in body["races"] if r["id"] == "councillor-1")
    assert row["state"] == "counting" and row["projection"] is None
    assert "councillor-1" not in draws


def test_a_bundle_without_projection_inputs_keeps_the_stub(replay_2022, nights):
    snap, _ = replay_2022
    body, _ = project(snap.all_office, snap.ward_by_ward, night_bundle(nights[2022]))
    council = next(r for r in body["races"] if r["id"] == "councillor-1")
    assert council["projection"]["stub"] is True


def test_projecting_only_some_races_gives_them_the_same_draws(replay_2022):
    # Replays score a few races per snapshot; each race's draws must not depend on the others.
    snap, bundle = replay_2022
    _, full = project(snap.all_office, snap.ward_by_ward, bundle)
    _, some = project(snap.all_office, snap.ward_by_ward, bundle, only={"councillor-5", "tdsb-3"})
    modelled = {r for r in some if not r.startswith("mayor")}
    assert modelled == {"councillor-5", "tdsb-3"}
    for race in some:
        assert np.array_equal(some[race]["count_only"][1], full[race]["count_only"][1])


def test_a_race_without_ward_aggregates_still_projects():
    inputs = RaceInputs((WardInputs("1", 20_000.0, 10, ()),))
    final = draws(4, votes=np.array([1_500, 900, 600]), inputs=inputs)
    assert final is not None and final.shape == (10_000, 3)


def aggregates_in(wards: int) -> RaceInputs:
    aggregates = tuple(Aggregate(c, 500.0, None, 0.2) for c in (97, 98, 99))
    return RaceInputs(tuple(WardInputs(str(w), 20_000.0, 10, aggregates) for w in range(wards)))


def test_an_area_of_five_city_wards_counts_aggregates_per_code():
    # 15 aggregates: 216 combinations of how many of each code are in, not 32,768 subsets.
    posterior = aggregate_posterior(aggregates_in(5), PARAMS, received=12, counted=3_000)
    assert len(posterior) == 6**3
    assert draws(12, inputs=aggregates_in(5)) is not None


def test_too_many_combinations_fail_closed():
    assert draws(30, inputs=aggregates_in(20)) is None  # 21^3 = 9,261 combinations


def test_outstanding_aggregates_are_less_certain_when_fewer_units_were_counted():
    # Every election-day unit in and every aggregate out: the aggregates' split is centred on
    # the counted shares, which two units pin down far less well than forty.
    votes = np.array([3_000, 2_000, 1_000])
    width = {}
    for units in (2, 40):
        final = draws(units, votes=votes, inputs=one_ward(units=units, spread=0.2))
        low, high = np.percentile(final[:, 0], [5, 95])
        width[units] = high - low
    assert width[2] > 1.5 * width[40]


def test_skipping_races_never_changes_a_stub_race(replay_2022, nights):
    snap, _ = replay_2022
    bundle = night_bundle(nights[2022])  # every level on stubs
    full, _ = project(snap.all_office, snap.ward_by_ward, bundle)
    some, _ = project(snap.all_office, snap.ward_by_ward, bundle, only={"tdsb-3"})
    pick = {r["id"]: r["projection"] for r in some["races"]}
    assert pick["tdsb-3"] == next(r for r in full["races"] if r["id"] == "tdsb-3")["projection"]
