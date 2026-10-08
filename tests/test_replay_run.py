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

    def at_the_truth(all_office, ward_by_ward, bundle):
        body, draws = real_project(all_office, ward_by_ward, bundle)
        for rid, variants in draws.items():
            race = next(r for r in night.races if race_id(r.office_id, r.num) == rid)
            certified = dict(zip(race.candidates, 100 * race.certified / race.certified.sum()))
            for v, (keys, _) in variants.items():
                variants[v] = (keys, np.array([[certified[k] for k in keys]]))
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
