"""The pre-registration file and the S3 stress-test shift (spec #17 § Pre-registered gates; #23)."""

import json
from pathlib import Path

import numpy as np
import pytest

from election_night.gates import (
    Holdout,
    forecast_margin,
    forecast_pair,
    load_preregistration,
    read_forecasts,
    s3_shift,
    sha256,
)

ROOT = Path(__file__).parent.parent
PREREG = ROOT / "gates" / "preregistration.json"


def _holdout(campaign, full_ballot, ids, actual):
    return Holdout(campaign, np.asarray(full_ballot, dtype=float), list(ids), actual)


def test_pair_is_the_top_two_by_win_probability_not_by_mean_share():
    # B wins 2 of 3 draws but A has the higher mean share; C never wins.
    full = np.array([[0.70, 0.20, 0.10], [0.30, 0.40, 0.30], [0.30, 0.35, 0.35]])
    assert forecast_pair(full) == (1, 0)


def test_pair_breaks_win_probability_ties_by_column_order():
    full = np.array([[0.2, 0.5, 0.3], [0.2, 0.3, 0.5]])
    assert forecast_pair(full) == (1, 2)


def test_error_is_median_draw_margin_against_actual_margin_in_points():
    full = [[0.50, 0.40], [0.55, 0.40], [0.60, 0.40]]  # margins 10, 15, 20: median 15
    shift, rows = s3_shift([_holdout("x", full, ["a", "b"], {"a": 0.48, "b": 0.42})])
    assert rows[0]["leader_candidate_id"] == "a"
    assert rows[0]["challenger_candidate_id"] == "b"
    assert rows[0]["median_margin_points"] == pytest.approx(15.0)
    assert rows[0]["actual_margin_points"] == pytest.approx(6.0)
    assert rows[0]["absolute_error_points"] == pytest.approx(9.0)
    assert shift == pytest.approx(9.0)


def test_actual_margin_is_signed_when_the_challenger_wins():
    full = [[0.55, 0.45]] * 3  # median margin 10
    _, rows = s3_shift([_holdout("x", full, ["a", "b"], {"a": 0.40, "b": 0.52})])
    assert rows[0]["actual_margin_points"] == pytest.approx(-12.0)
    assert rows[0]["absolute_error_points"] == pytest.approx(22.0)


def test_shift_is_the_90th_percentile_by_linear_interpolation():
    # Errors 1..7: rank 0.9 * 6 = 5.4 lies between 6 and 7, so 6.4.
    holdouts = [
        _holdout(f"c{e}", [[0.5 + e / 100, 0.5]], ["a", "b"], {"a": 0.5, "b": 0.5})
        for e in (3, 1, 7, 5, 2, 6, 4)
    ]
    shift, rows = s3_shift(holdouts)
    assert [r["absolute_error_points"] for r in rows] == pytest.approx([3, 1, 7, 5, 2, 6, 4])
    assert shift == pytest.approx(6.4)


def test_loader_rejects_a_file_missing_a_section(tmp_path):
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    del prereg["stress_test_shift"]
    path = tmp_path / "p.json"
    path.write_text(json.dumps(prereg))
    with pytest.raises(ValueError, match="stress_test_shift"):
        load_preregistration(path)


def test_file_reads_back_with_every_gate_in_spec_17():
    p = load_preregistration(PREREG)
    assert p["nights"]["mayor"]["years"] == [2014, 2018, 2022, 2023]
    assert (p["nights"]["council"]["races"], p["nights"]["trustee"]["races"]) == (94, 102)
    assert p["checkpoints"]["reporting_progress_percent"] == list(range(5, 100, 5))
    orders = p["arrival_orders"]
    patterns = orders["ward_aggregates"]["timing_patterns"]
    assert set(patterns) == {"early", "interleaved", "late"}
    assert orders["orders_per_night"] == len(patterns) * orders["orders_per_pattern"] == 60
    assert isinstance(orders["seeds"]["root"], int)
    assert [c["id"] for c in p["pass_criteria"]["criteria"]] == [1, 2, 3, 4, 5, 6]
    ess = p["forecast_weighted_variant"]["ess_fallback"]
    assert (ess["threshold"], ess["of_draws"]) == (1000, 10000)
    assert p["fitting"]["draws_per_projection"] == ess["of_draws"]
    assert p["forecast_density"]["bandwidth"] == "Silverman's rule"
    assert set(p["ward_aggregate_paths"]["nights"]) == {"2014", "2018", "2022", "2023"}


def test_recorded_s3_shift_is_the_90th_percentile_of_its_recorded_inputs():
    s3 = load_preregistration(PREREG)["stress_test_shift"]
    errors = [c["absolute_error_points"] for c in s3["campaigns"]]
    assert len(errors) == 7
    for c in s3["campaigns"]:
        assert c["absolute_error_points"] == pytest.approx(
            abs(c["median_margin_points"] - c["actual_margin_points"]), abs=1e-5
        )
    assert s3["shift_points"] == pytest.approx(np.percentile(errors, 90), abs=1e-5)


def test_recorded_s3_forecast_side_matches_the_vendored_draws():
    s3 = load_preregistration(PREREG)["stress_test_shift"]
    forecasts = ROOT / s3["sources"]["forecasts_dir"]
    assert s3["sources"]["forecasts"] == {
        p.name: sha256(p) for p in sorted(forecasts.glob("toronto_*.json"))
    }
    recorded = {c["campaign"]: c for c in s3["campaigns"]}
    vendored = read_forecasts(forecasts)
    assert sorted(recorded) == [campaign for campaign, _, _ in vendored]
    for campaign, ids, full in vendored:
        leader, challenger, median = forecast_margin(full)
        c = recorded[campaign]
        assert (ids[leader], ids[challenger]) == (
            c["leader_candidate_id"],
            c["challenger_candidate_id"],
        )
        assert c["median_margin_points"] == pytest.approx(median, abs=1e-5)


def test_recorded_inputs_match_the_files_in_the_repo():
    p = load_preregistration(PREREG)
    captures = p["real_captures"]["mayor"] + p["real_captures"]["council_and_trustee"]
    for capture in captures:
        assert sha256(ROOT / capture["path"]) == capture["sha256"]
    paths = p["ward_aggregate_paths"]
    assert sha256(ROOT / paths["source"]) == paths["source_sha256"]
