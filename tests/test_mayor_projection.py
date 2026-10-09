"""The mayor's count-extension projection: City ward units summed to the citywide result (#36)."""

import json

import numpy as np
import pytest

from election_night.gates import load_preregistration
from election_night.payload import build_payload, project
from election_night.projection.count_extension import (
    Aggregate,
    MayorParams,
    RaceInputs,
    WardInputs,
    draw_mayor_final_shares,
    mayor_final_votes,
)
from election_night.projection.fit import fit_mayor
from election_night.projection.history import replay_bundle
from election_night.replay.historical import YEARS, load_night
from election_night.replay.orders import arrival_order
from election_night.replay.run import PREREGISTRATION
from election_night.replay.snapshots import snapshots

PARAMS = MayorParams(kappa=50.0, size_cv=0.3, tau=40.0, omega_city=30.0, omega_ward=300.0)
TIGHT = MayorParams(kappa=1e6, size_cv=0.01, tau=1e6, omega_city=1e6, omega_ward=1e6)


def advance(votes: float) -> tuple[Aggregate, ...]:
    return (Aggregate(98, votes, None, 0.05), Aggregate(99, votes, None, 0.05))


def ward(num: str, base: float, units: int = 10, aggregates=()) -> WardInputs:
    return WardInputs(num, base, units, tuple(aggregates))


def run(inputs, votes, received, params=PARAMS, seed=7, per_ward=False, draws=2_000):
    rng = np.random.default_rng(seed)
    votes = np.asarray(votes, dtype=float)
    return mayor_final_votes(inputs, params, votes, np.asarray(received), rng, draws, per_ward)


def test_a_ward_with_nothing_counted_is_centred_on_the_citywide_counted_shares():
    # Ward 1 has 9 of 10 units in at 60-40; Ward 2, twice its size, has nothing in. Centred on
    # the citywide shares, Ward 2 also splits 60-40; centred on its own (empty) count it would
    # split 50-50 and pull the result toward 53%.
    inputs = RaceInputs((ward("1", 20_000.0), ward("2", 40_000.0)))
    votes = [[5_400, 3_600], [0, 0]]
    city, _ = run(inputs, votes, [9, 0], params=TIGHT)
    shares = 100 * city / city.sum(axis=1, keepdims=True)

    assert np.abs(shares[:, 0] - 60.0).max() < 0.5


def test_the_citywide_result_is_the_sum_of_the_wards():
    inputs = RaceInputs(
        (
            ward("1", 20_000.0, aggregates=advance(800.0)),  # every unit in
            ward("2", 30_000.0, aggregates=advance(1_000.0)),  # partly in
            ward("3", 25_000.0, aggregates=advance(900.0)),  # nothing in
        )
    )
    votes = np.array([[4_000, 3_000, 500], [2_000, 2_500, 100], [0, 0, 0]], dtype=float)
    city, wards = run(inputs, votes, [12, 5, 0], per_ward=True)

    assert len(wards) == 3
    assert np.array_equal(wards[0], np.broadcast_to(votes[0], wards[0].shape))
    for counted, final in zip(votes, wards):
        assert (final >= counted - 1e-9).all()
    assert np.allclose(city, sum(wards))
    shares = draw_mayor_final_shares(
        inputs, PARAMS, votes, np.array([12, 5, 0]), np.random.default_rng(7), draws=2_000
    )
    assert np.allclose(shares, 100 * city / city.sum(axis=1, keepdims=True))


def test_draws_are_deterministic_and_absent_at_the_start_and_end():
    inputs = RaceInputs((ward("1", 20_000.0, aggregates=advance(800.0)), ward("2", 30_000.0)))
    votes = [[300, 200], [100, 50]]
    first, _ = run(inputs, votes, [3, 1])
    again, _ = run(inputs, votes, [3, 1])
    assert np.array_equal(first, again)
    assert run(inputs, [[0, 0], [0, 0]], [0, 0]) is None
    assert run(inputs, votes, [12, 10]) is None


def test_the_early_vote_shift_is_shared_by_every_ward():
    # Both wards have every election-day unit in and their advance votes out: aggregates of
    # 5,000 can't hide in a count of 5,000. The citywide shift is wide and the ward-level noise
    # tight, so the two wards' early votes move together.
    inputs = RaceInputs(
        (
            ward("1", 50_000.0, aggregates=advance(5_000.0)),
            ward("2", 50_000.0, aggregates=advance(5_000.0)),
        )
    )
    votes = np.array([[2_500, 2_500], [2_500, 2_500]], dtype=float)
    params = MayorParams(kappa=1e4, size_cv=0.01, tau=1e4, omega_city=10.0, omega_ward=1e5)
    _, wards = run(inputs, votes, [10, 10], params=params, per_ward=True)
    early = [(w - c)[:, 0] / (w - c).sum(axis=1) for w, c in zip(wards, votes)]

    assert np.std(early[0]) > 0.05
    assert np.corrcoef(early[0], early[1])[0, 1] > 0.95


# Per-fold fitting and the payload, on the real historical files.

PREREG = load_preregistration(PREREGISTRATION)


@pytest.fixture(scope="module")
def nights():
    return {year: load_night(year, PREREG) for year in YEARS}


def test_each_fold_fits_the_mayors_parameters(nights):
    for year in (2014, 2018, 2022, 2023):
        params = fit_mayor([n for y, n in nights.items() if y != year])
        assert all(v > 0 for v in vars(params).values())


@pytest.fixture(scope="module")
def replay_2023(nights):
    night = nights[2023]
    bundle = replay_bundle(night, nights, PREREG)
    order = arrival_order(night, PREREG, "interleaved", 0)
    (snap,) = snapshots(night, order, steps=[len(order) // 2])
    return snap, bundle


def test_a_counting_mayor_carries_the_models_count_only_bands(replay_2023):
    snap, bundle = replay_2023
    body, draws = project(snap.all_office, snap.ward_by_ward, bundle)
    mayor = next(r for r in body["races"] if r["id"] == "mayor")
    keys = [c["key"] for c in mayor["candidates"]]

    assert mayor["state"] == "counting"
    assert mayor["projection"]["stub"] is False
    assert list(mayor["projection"]["bands"]) == ["count_only"]
    assert list(mayor["projection"]["bands"]["count_only"]) == keys
    assert draws["mayor"]["count_only"][1].shape == (10_000, len(keys))
    assert build_payload(snap.all_office, snap.ward_by_ward, bundle) == build_payload(
        snap.all_office, snap.ward_by_ward, bundle
    )


def test_a_ward_whose_inputs_dont_match_its_units_fails_the_mayor_closed(replay_2023):
    snap, bundle = replay_2023
    broken = json.loads(json.dumps(bundle))
    mayor = next(r for r in broken["races"] if r["id"] == "mayor")
    mayor["expected"]["wards"][3]["election_day_units"] += 1
    body, draws = project(snap.all_office, snap.ward_by_ward, broken)

    assert next(r for r in body["races"] if r["id"] == "mayor")["projection"] is None
    assert "mayor" not in draws
