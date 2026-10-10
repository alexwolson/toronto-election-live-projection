"""The Replay harness on a tiny hand-built night: generator -> payload function -> scorer (#29)."""

import json
from pathlib import Path

import numpy as np
import pytest

from election_night import payload
from election_night.feed import race_id
from election_night.gates import load_preregistration
from election_night.replay.captures import Capture
from election_night.replay.historical import Night, Race, Unit
from election_night.replay.orders import arrival_order
from election_night.replay.run import LEVELS, capture_cases, order_cases, replay_level
from election_night.replay.snapshots import snapshots

ROOT = Path(__file__).parent.parent
PREREG = load_preregistration(ROOT / "gates" / "preregistration.json")
PERCENTS = PREREG["checkpoints"]["reporting_progress_percent"]


def _race(office_id, num, name, candidates, units, rng):
    votes = rng.integers(0, 200, size=(len(units), len(candidates)))
    votes[:, 0] += 30  # the first candidate wins
    return Race(office_id, num, name, candidates, tuple(units), votes, votes.sum(axis=0))


def tiny_night(year=2022) -> Night:
    """Two wards of 20 election-day units and one Ward Aggregate each: a mayor, two councillor
    races (Ward 2's acclaimed) and one trustee race across both wards."""
    rng = np.random.default_rng(7)
    ward = {w: [(w, c) for c in range(1, 21)] + [(w, 97)] for w in (1, 2)}
    every = ward[1] + ward[2]
    races = (
        _race(1, "0", "City-wide", ("Chow Olivia", "Bailão Ana", "Saunders Mark"), every, rng),
        _race(2, "1", "Ward A", ("Fletcher Paula", "Lin Tony"), ward[1], rng),
        _race(2, "2", "Ward B", ("Perks Gord",), ward[2], rng),
        _race(3, "1", None, ("Smith Ann", "Lee Bo", "Ng Cy"), every, rng),
    )
    return Night(
        year=year,
        opening_time="2022-10-24T20:00:00-04:00",
        election_desc="2022 Municipal Election",
        units=tuple(Unit(w, c, c == 97) for w, c in every),
        wards=((1, "Ward A"), (2, "Ward B")),
        races=races,
    )


def _order(night, index=0):
    return arrival_order(night, PREREG, "interleaved", index)


def test_each_scored_race_gets_every_checkpoint_and_acclaimed_races_none():
    night = tiny_night()
    cases = order_cases(night, _order(night), "interleaved-0", LEVELS["council"], PREREG, "v")

    assert {c.race for c in cases} == {"councillor-1"}  # Ward 2 is acclaimed
    assert [c.checkpoint for c in cases] == [f"{p}%" for p in PERCENTS]
    assert {c.order for c in cases} == {"interleaved-0"}


def test_a_case_scores_the_payload_functions_own_draws_against_the_certified_count():
    night = tiny_night()
    cases = order_cases(night, _order(night), "interleaved-0", LEVELS["trustee"], PREREG, "v")
    trustee_race = night.races[3]
    final = 100 * trustee_race.certified / trustee_race.certified.sum()

    for case in cases:
        assert case.draws.shape == (payload.STUB_DRAWS, 3)
        # Candidates line up: the final shares are the certified ones in the case's own order.
        assert sorted(case.final.tolist()) == pytest.approx(sorted(final.tolist()))
        assert case.tally.sum() == pytest.approx(100.0)


def test_a_projection_at_the_truth_passes_and_the_tally_alone_does_not(monkeypatch):
    night = tiny_night()
    nights = {2014: tiny_night(2014), 2018: tiny_night(2018), 2022: night}
    orders = {y: [("interleaved", 0, _order(n))] for y, n in nights.items()}

    def at_the_truth(all_office, ward_by_ward, bundle, only=None):
        body, draws = real_project(all_office, ward_by_ward, bundle, only)
        for rid, variants in draws.items():
            race = next(r for r in night.races if race_id(r.office_id, r.num) == rid)
            certified = dict(zip(race.candidates, 100 * race.certified / race.certified.sum()))
            for v, (keys, _, _) in variants.items():
                variants[v] = (keys, np.array([[certified[k] for k in keys]]), None)
        return body, draws

    real_project = payload.project
    result = replay_level("council", PREREG, nights, orders, [], "v", project=at_the_truth)

    assert result["pass"] is True
    assert result["scores"]["total"]["margin_crps"] == 0.0
    assert {c["id"] for c in result["criteria"]} == {1, 2, 3, 4, 5}
    assert result["cases"] == 3 * len(PERCENTS)
    assert result["level"] == "council" and result["variant"] == "count_only"


def test_stress_orders_are_reported_and_never_decide():
    nights = {2022: tiny_night()}
    night = nights[2022]
    orders = {
        2022: [
            ("interleaved", 0, _order(night)),
            ("ward_clustered", 0, arrival_order(night, PREREG, "ward_clustered", 0)),
        ]
    }
    result = replay_level("council", PREREG, nights, orders, [], "v")

    assert result["cases"] == len(PERCENTS)  # the pattern order only
    assert result["reported"]["stress_orders"]["cases"] == len(PERCENTS)
    assert result["orders_per_night"] == {"timing_patterns": 1, "stress": 1}


def test_a_capture_name_the_certified_count_leaves_out_finishes_at_zero():
    # 2022 Ward 23 lists Cynthia Lai, who died during the campaign, at 0 (captures.py).
    night = tiny_night()
    order = _order(night)
    snap = next(snapshots(night, order, steps=[len(order) // 2]))
    data = json.loads(snap.all_office)
    row = next(w for o in data["office"] if o["id"] == 2 for w in o["ward"] if w["num"] == "1")
    row["candidate"].append({"name": "Lai Cynthia", "votesReceived": "0", "percentage": "0.00"})
    capture = Capture(
        2022, "2022-10-24T21:09", "all-office", json.dumps(data).encode(), snap.ward_by_ward
    )

    (case,) = capture_cases(night, capture, LEVELS["council"], PREREG, "v")

    assert case.checkpoint == "capture 2022-10-24T21:09" and case.order is None
    assert case.final.size == 3 and case.final[-1] == 0.0
    assert case.final.sum() == pytest.approx(100.0)


def test_mayor_gate_results_carry_the_bailao_check_and_fail_it_without_the_capture():
    nights = {2023: tiny_night(2023)}
    orders = {2023: [("interleaved", 0, _order(nights[2023]))]}
    result = replay_level("mayor-count-only", PREREG, nights, orders, [], "v")
    six = next(c for c in result["criteria"] if c["id"] == 6)

    assert six["value"] is None and six["pass"] is False
    assert result["pass"] is False


def test_the_bailao_check_reads_her_win_probability_at_the_capture():
    night = tiny_night(2023)
    order = _order(night)
    snap = next(snapshots(night, order, steps=[len(order) // 2]))
    capture = Capture(2023, "2023-06-26T20:26", "ward-by-ward", snap.all_office, snap.ward_by_ward)
    orders = {2023: [("interleaved", 0, order)]}
    result = replay_level("mayor-count-only", PREREG, {2023: night}, orders, [capture], "v")
    six = next(c for c in result["criteria"] if c["id"] == 6)

    assert six["value"] is not None and 0.0 <= six["value"] <= 1.0
    assert isinstance(six["pass"], bool)


# The mayor's forecast-weighted variant (#41): the count-only draws reweighted, on the same
# orders and draws, with the ESS fallback and the wrong-forecast stress test inside.


def modelled_tiny_bundle(night, margins):
    """The tiny night's bundle with the mayor modelled and a forecast density over Chow minus
    Bailão whose margin draws are `margins` points."""
    from election_night.projection.forecast_weighted import ForecastDensity, silverman_bandwidth
    from election_night.replay.snapshots import night_bundle

    bundle = night_bundle(night)
    bundle["projection"] = {
        "params": {
            "mayor": {
                "kappa": 50.0,
                "size_cv": 0.3,
                "tau": 40.0,
                "omega_city": 30.0,
                "omega_ward": 300.0,
            }
        }
    }
    mayor = next(r for r in bundle["races"] if r["id"] == "mayor")
    mayor["expected"] = {
        "wards": [
            {
                "ward": w,
                "base": 15_000.0,
                "election_day_units": 20,
                "aggregates": [{"code": 97, "votes": None, "share": 0.05, "spread": 0.2}],
            }
            for w in ("1", "2")
        ]
    }
    margins = np.asarray(margins, dtype=float)
    bundle["forecast_density"] = ForecastDensity(
        "Chow Olivia", "Bailão Ana", margins, silverman_bandwidth(margins)
    )
    return bundle


def variant_run(margins, project=payload.project, years=(2023,)):
    nights = {year: tiny_night(year) for year in years}
    orders = {year: [("interleaved", 0, _order(night))] for year, night in nights.items()}
    order = orders[2023][0][2]
    snap = next(snapshots(nights[2023], order, steps=[len(order) // 2]))
    capture = Capture(2023, "2023-06-26T20:26", "ward-by-ward", snap.all_office, snap.ward_by_ward)
    return replay_level(
        "mayor-forecast-weighted",
        PREREG,
        nights,
        orders,
        [capture],
        "v",
        project=project,
        make_bundle=lambda n: modelled_tiny_bundle(n, margins),
    )


def test_the_variant_gate_result_holds_the_ladder_and_the_stress_test():
    margins = np.random.default_rng(1).normal(10, 30, 2_000)  # broad: the weights stay spread
    result = variant_run(margins)
    ids = [c["id"] for c in result["criteria"]]

    assert result["level"] == "mayor-forecast-weighted"
    assert result["variant"] == "forecast_weighted"
    assert ids == [1, 2, 3, 4, 5, 6, "beats_count_only", "stress_g1", "stress_bailao"]
    assert result["pass"] == all(c["pass"] for c in result["criteria"])
    beats = next(c for c in result["criteria"] if c["id"] == "beats_count_only")
    assert (
        beats["value"]["total"]["count_only"]
        == result["reported"]["count_only"]["scores"]["total"]["margin_crps"]
    )
    assert result["reported"]["count_only"]["cases"] == result["cases"]
    assert (
        result["reported"]["stress_test"]["shift_points"]
        == PREREG["stress_test_shift"]["shift_points"]
    )
    switching = result["reported"]["switching"]["forecast_weighted"]
    assert switching["checkpoints"] == len(PERCENTS)  # the order's own; the capture isn't one
    assert switching["fallback_checkpoints"] == 0
    assert result["scores"]["total"]["margin_crps"] != beats["value"]["total"]["count_only"]


def collapsed(truth_of):
    """A projection whose count-only draws are one row, `truth_of(race)`'s shares, so every
    forecast weighting has an ESS of 1 and every refresh falls back."""

    def project(all_office, ward_by_ward, bundle, only=None):
        body, draws = payload.project(all_office, ward_by_ward, bundle, only)
        night = tiny_night(2023)
        for rid, variants in draws.items():
            race = next(r for r in night.races if race_id(r.office_id, r.num) == rid)
            shares = dict(zip(race.candidates, truth_of(race)))
            keys = variants["count_only"][0]
            row = np.array([[shares[k] for k in keys]])
            variants.clear()
            variants["count_only"] = (keys, row, None)
            variants["forecast_weighted"] = (keys, row, np.ones(1))
        for race in body["races"]:
            if race["projection"] and "variant" in race["projection"]:
                race["projection"]["variant"] = {
                    "in_effect": "count_only",
                    "ess": 1.0,
                    "off_reason": "low_ess",
                }
        return body, draws

    return project


def test_below_the_ess_floor_the_variant_scores_count_only_when_count_only_passed():
    truth = collapsed(lambda race: 100 * race.certified / race.certified.sum())
    margins = np.random.default_rng(1).normal(10, 30, 2_000)
    result = variant_run(margins, project=truth, years=(2014, 2018, 2022, 2023))

    assert result["reported"]["count_only"]["pass"] is True
    assert result["scores"]["total"]["margin_crps"] == 0.0
    switching = result["reported"]["switching"]
    assert switching["forecast_weighted"]["fallback_checkpoints"] == 4 * len(PERCENTS)
    assert switching["stress_test"]["fallback_checkpoints"] == 4 * len(PERCENTS)
    assert switching["forecast_weighted"]["switches"] == 0


def test_below_the_ess_floor_the_variant_scores_the_tally_when_count_only_failed():
    reversed_ = collapsed(lambda race: 100 * race.certified[::-1] / race.certified.sum())
    result = variant_run(np.random.default_rng(1).normal(10, 30, 2_000), project=reversed_)
    total = result["scores"]["total"]

    assert result["reported"]["count_only"]["pass"] is False
    assert total["margin_crps"] == pytest.approx(total["baseline_margin_error"])
    assert total["brier"] == pytest.approx(total["baseline_brier"])


def test_orders_replayed_by_parallel_workers_give_the_same_gate_result():
    # #44: the orders fan out over a process pool and come back in their own order.
    nights = {2018: tiny_night(2018), 2022: tiny_night(2022)}
    orders = {
        y: [
            ("interleaved", 0, _order(n)),
            ("early", 0, arrival_order(n, PREREG, "early", 0)),
            ("ward_clustered", 0, arrival_order(n, PREREG, "ward_clustered", 0)),
        ]
        for y, n in nights.items()
    }
    serial = replay_level("council", PREREG, nights, orders, [], "v")
    parallel = replay_level("council", PREREG, nights, orders, [], "v", workers=2)

    assert json.dumps(parallel, sort_keys=True) == json.dumps(serial, sort_keys=True)
