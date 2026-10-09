"""The Replay scorer on tiny hand-built nights (spec #17 § Testing Decisions, seam 2; ticket #29).

Shares are in points. Candidates are listed in the same order in a case's draws, tally and final
count; the eventual winner and runner-up come from the final count.
"""

import dataclasses
from pathlib import Path

import numpy as np
import pytest

from election_night.gates import load_preregistration
from election_night.replay.scoring import (
    Case,
    bailao_check,
    checkpoint_steps,
    criteria,
    crps,
    night_scores,
    score_case,
    totals,
)

ROOT = Path(__file__).parent.parent
PREREG = load_preregistration(ROOT / "gates" / "preregistration.json")
CONFIDENCE = 0.95
MASS = 0.9


def _case(draws, tally, final, night=2022, race="councillor-1", order="early-0") -> Case:
    return Case(
        night=night,
        race=race,
        checkpoint="50%",
        order=order,
        draws=np.atleast_2d(np.asarray(draws, dtype=float)),
        tally=np.asarray(tally, dtype=float),
        final=np.asarray(final, dtype=float),
    )


def _score(case):
    return score_case(case, confidence=CONFIDENCE, interval_mass=MASS)


# CRPS


def test_crps_of_a_point_mass_is_its_absolute_error():
    assert crps(np.array([3.0]), 7.5) == pytest.approx(4.5)
    assert crps(np.array([3.0, 3.0, 3.0]), -1.0) == pytest.approx(4.0)


def test_crps_of_two_draws_matches_its_definition():
    # E|X - y| - E|X - X'| / 2 = 0.5 - 0.25
    assert crps(np.array([0.0, 1.0]), 0.0) == pytest.approx(0.25)


# One case


def test_the_tally_baselines_margin_crps_equals_its_absolute_margin_error():
    tally, final = [40.0, 45.0, 15.0], [50.0, 38.0, 12.0]
    score = _score(_case([tally], tally, final))

    # Winner A over runner-up B: the tally's margin is -5, the final margin 12.
    assert score.baseline_margin_error == pytest.approx(17.0)
    assert score.margin_crps == pytest.approx(score.baseline_margin_error)
    assert score.brier == pytest.approx(score.baseline_brier) == pytest.approx(2.0)


def test_a_point_mass_at_the_truth_scores_zero():
    final = [50.0, 38.0, 12.0]
    score = _score(_case([final] * 5, [45.0, 40.0, 15.0], final))

    assert score.margin_crps == 0.0
    assert score.share_crps == 0.0
    assert score.brier == 0.0
    assert score.baseline_brier == 0.0  # the tally's leader is the winner
    assert score.g1_calls == 1 and score.g1_hits == 1
    assert score.g2_margin and score.g2_shares == 3


def test_the_margin_is_signed_and_negative_where_the_order_is_reversed():
    final = [50.0, 40.0, 10.0]  # final margin +10
    reversed_draws = [[40.0, 50.0, 10.0]] * 4  # margin -10 in every draw
    score = _score(_case(reversed_draws, [50.0, 40.0, 10.0], final))

    assert score.margin_crps == pytest.approx(20.0)


def test_brier_reads_win_probabilities_from_the_draws():
    final = [50.0, 40.0, 10.0]
    draws = [[50, 40, 10], [50, 40, 10], [50, 40, 10], [40, 50, 10]]  # A 3 of 4, B 1 of 4
    score = _score(_case(draws, [40.0, 50.0, 10.0], final))

    assert score.brier == pytest.approx(0.25**2 + 0.25**2)
    assert score.baseline_brier == pytest.approx(2.0)  # the tally's leader, B, lost


def test_g1_counts_only_candidates_given_at_least_the_confidence():
    final = [50.0, 40.0, 10.0]
    sure_wrong = [[40, 50, 10]] * 19 + [[50, 40, 10]]  # B at 0.95, and B loses
    unsure = [[40, 50, 10]] * 18 + [[50, 40, 10]] * 2  # B at 0.90: no call

    wrong = _score(_case(sure_wrong, [40, 50, 10], final))
    none = _score(_case(unsure, [40, 50, 10], final))

    assert (wrong.g1_calls, wrong.g1_hits) == (1, 0)
    assert (none.g1_calls, none.g1_hits) == (0, 0)


def test_g2_checks_the_central_range_of_the_margin_and_of_each_share():
    final = [50.0, 40.0, 10.0]  # margin 10
    # A's share runs 41..60, B's stays 40, C's stays 20: the margin runs 1..20.
    draws = [[a, 40.0, 20.0] for a in np.linspace(41, 60, 101)]
    score = _score(_case(draws, [45, 40, 15], final))

    assert score.g2_margin  # 10 is inside the margin's 5-95% range
    assert score.g2_shares == 2  # A's 50 and B's 40 are in; C's 10 is not
    assert score.candidates == 3


# Nights and criteria


def _night(night, races):
    """Cases for one night: {race: [(margin draws offset, ...)]} built from a fixed final."""
    final = [50.0, 40.0, 10.0]
    cases = []
    for race, offsets in races.items():
        for i, offset in enumerate(offsets):
            draws = [[50 + offset, 40, 10]]
            cases.append(_case(draws, final, final, night=night, race=race, order=f"o-{i}"))
    return cases


def test_races_are_weighted_equally_within_a_night_and_nights_equally():
    cases = _night(2018, {"r1": [2.0, 4.0], "r2": [6.0]}) + _night(2022, {"r1": [1.0]})
    nights = night_scores([_score(c) for c in cases])

    assert nights[2018]["margin_crps"] == pytest.approx((3.0 + 6.0) / 2)
    assert nights[2018]["races"] == 2 and nights[2018]["cases"] == 3
    assert totals(nights)["margin_crps"] == pytest.approx((4.5 + 1.0) / 2)


def test_g1_pools_cases_within_a_night_and_leaves_out_a_night_without_calls():
    final = [50.0, 40.0, 10.0]
    hit = _case([final], final, final, night=2018, order="a")
    miss = _case([[40, 50, 10]], final, final, night=2018, order="b")
    hit2 = _case([final], final, final, night=2018, order="c")
    no_call = _case([[50, 40, 10], [40, 50, 10]], final, final, night=2022)
    nights = night_scores([_score(c) for c in (hit, miss, hit2, no_call)])

    assert nights[2018]["g1"] == pytest.approx(2 / 3)
    assert nights[2022]["g1"] is None
    assert totals(nights)["g1"] == pytest.approx(2 / 3)


def test_cases_whose_projection_has_retired_are_counted():
    final = [50.0, 40.0, 10.0]
    retired = Case(2022, "r", "95%", "o", np.array([final]), np.array(final), np.array(final), True)
    nights = night_scores([_score(retired), _score(_case([final], final, final))])

    assert nights[2022]["retired_cases"] == 1


def test_g1_is_null_when_no_night_has_a_call():
    final = [50.0, 40.0, 10.0]
    nights = night_scores([_score(_case([[50, 40, 10], [40, 50, 10]], final, final))])

    assert totals(nights)["g1"] is None


def _criteria(cases, level="council"):
    nights = night_scores([_score(c) for c in cases])
    return {c["id"]: c for c in criteria(nights, PREREG, level)}


def test_criteria_1_to_5_pass_for_a_projection_at_the_truth():
    final = [50.0, 40.0, 10.0]
    tally = [45.0, 44.0, 11.0]
    cases = [_case([final], tally, final, night=y) for y in (2014, 2018, 2022)]
    result = _criteria(cases)

    assert sorted(result) == [1, 2, 3, 4, 5]
    assert all(c["pass"] for c in result.values())
    assert result[2]["value"] == 3 and result[2]["threshold"] == 2


def test_the_tally_itself_fails_criterion_1_and_meets_criterion_3():
    final, tally = [50.0, 40.0, 10.0], [45.0, 44.0, 11.0]
    cases = [_case([tally], tally, final, night=y) for y in (2014, 2018, 2022)]
    result = _criteria(cases)

    assert not result[1]["pass"]  # equal is not below
    assert not result[2]["pass"]
    assert result[3]["pass"]  # equal is not worse


def test_criterion_2_needs_the_pre_registered_majority_of_nights():
    final, tally = [50.0, 40.0, 10.0], [45.0, 44.0, 11.0]
    good = [_case([final], tally, final, night=y) for y in (2014, 2018)]
    bad = [_case([[20, 70, 10]], tally, final, night=y) for y in (2022, 2023)]
    result = _criteria(good + bad, level="mayor")

    assert result[2]["value"] == 2 and result[2]["threshold"] == 3
    assert not result[2]["pass"]


def test_criterion_5_holds_the_margin_and_the_shares_to_the_threshold_separately():
    final = [50.0, 40.0, 10.0]
    # The margin's range always holds 10, but C's share never holds its final 10.
    draws = [[a, 40.0, 20.0] for a in np.linspace(41, 60, 101)]
    cases = [_case(draws, final, final, night=y) for y in (2014, 2018, 2022)]
    result = _criteria(cases)

    assert result[5]["value"] == {"margin": 1.0, "shares": pytest.approx(2 / 3)}
    assert not result[5]["pass"]


# The checkpoint grid


def test_each_checkpoint_is_the_first_step_at_or_after_its_reporting_progress():
    # A race with 10 units; one unit arrives at steps 2, 3, 5, 6, ... (others belong elsewhere).
    received = np.array([0, 0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    grid = dict(checkpoint_steps(received, units=10, percents=[5, 10, 15, 50, 95]))

    assert grid == {5: 2, 10: 2, 15: 3, 50: 7, 95: 12}


def test_the_grid_is_the_pre_registered_one():
    received = np.arange(101)
    percents = PREREG["checkpoints"]["reporting_progress_percent"]
    grid = checkpoint_steps(received, units=100, percents=percents)

    assert [p for p, _ in grid] == list(range(5, 100, 5))
    assert [s for _, s in grid] == list(range(5, 100, 5))


def test_g2_share_coverage_is_averaged_per_case_before_pooling():
    # A two-way race fully covered and a four-way race with one of four covered: per case, (1 +
    # 0.25) / 2, not 3 of 6 candidates. Decided by Alex on #29 (2026-10-08).
    two = _case([[60.0, 40.0]] * 3, [60.0, 40.0], [60.0, 40.0], race="a")
    four_draws = [[40.0, 30.0, 20.0, 10.0]] * 3
    four = _case(four_draws, [40, 30, 20, 10], [40.0, 25.0, 25.0, 10.0 - 0.0001], race="b")
    nights = night_scores([_score(two), _score(four)])

    assert nights[2022]["g2_shares"] == pytest.approx((1.0 + 0.25) / 2)


# Criterion 6, the Bailão check (#36)

CAPTURE = "capture 2023-06-26T20:26"
KEYS = ("Chow Olivia", "Bailão Ana", "Saunders Mark")


def _capture_case(bailao_wins: int, checkpoint=CAPTURE, night=2023) -> Case:
    # Of 10 draws, Bailão leads in `bailao_wins`, Chow in the rest.
    draws = [[30.0, 40.0, 30.0]] * bailao_wins + [[40.0, 30.0, 30.0]] * (10 - bailao_wins)
    final = [37.2, 32.5, 30.3]
    case = _case(draws, [35.2, 36.1, 28.7], final, night=night, race="mayor", order=None)
    return dataclasses.replace(case, checkpoint=checkpoint, keys=KEYS)


@pytest.mark.parametrize(("wins", "passes"), [(6, True), (7, False)])
def test_bailao_check_holds_bailaos_win_probability_at_the_capture_under_065(wins, passes):
    others = [_capture_case(10, checkpoint="50%")]  # an ordinary checkpoint never counts
    result = bailao_check(others + [_capture_case(wins)], PREREG, "Ana Bailão")

    assert result["id"] == 6 and result["threshold"] == 0.65
    assert result["value"] == pytest.approx(wins / 10)
    assert result["pass"] is passes


def test_bailao_check_fails_closed_without_the_capture():
    result = bailao_check([_capture_case(0, night=2022)], PREREG, "Ana Bailão")

    assert result["pass"] is False and result["value"] is None


# Weighted draws: the forecast-weighted variant scores the count-only draws reweighted (#41).


def test_weighted_crps_equals_the_crps_of_the_draws_repeated_by_their_weights():
    draws, weights = np.array([0.0, 1.0, 2.0, 5.0]), np.array([1.0, 2.0, 1.0, 3.0])
    repeated = np.repeat(draws, weights.astype(int))

    for observed in (-1.0, 1.5, 4.0):
        assert crps(draws, observed, weights / weights.sum()) == pytest.approx(
            crps(repeated, observed)
        )


def test_draws_of_weight_zero_score_as_if_absent():
    # The first two draws reverse the order; weighted away, the rest all have the winner ahead.
    draws = [[30.0, 60.0, 10.0], [35.0, 55.0, 10.0], [55.0, 35.0, 10.0], [58.0, 32.0, 10.0]]
    tally, final = [48.0, 42.0, 10.0], [56.0, 34.0, 10.0]
    kept = _score(_case(draws[2:], tally, final))
    weighted = _score(
        dataclasses.replace(_case(draws, tally, final), weights=np.array([0, 0, 0.5, 0.5]))
    )

    assert weighted.margin_crps == pytest.approx(kept.margin_crps)
    assert weighted.brier == pytest.approx(0.0) and kept.brier == pytest.approx(0.0)
    assert (weighted.g1_calls, weighted.g1_hits) == (1, 1)
    assert weighted.share_crps == pytest.approx(kept.share_crps)


def test_the_bailao_check_reads_the_weighted_share_of_draws_she_leads():
    case = _capture_case(5)  # Bailão leads in the first five of ten draws
    weights = np.array([0.1] * 5 + [0.02] * 5)  # 0.5 of the weight on her five
    weights = weights / weights.sum()
    result = bailao_check([dataclasses.replace(case, weights=weights)], PREREG, "Ana Bailão")

    assert result["value"] == pytest.approx(0.5 / 0.6)
