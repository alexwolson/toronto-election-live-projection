"""The 2026 Night Bundle (seam 3, #46): expected totals, Ward Aggregate sizes, the frozen
parameters and the pinned forecast draws, built from the committed inputs.

Each failure case edits a copy of the committed inputs, as a changed input would arrive.
"""

import json
import shutil
from pathlib import Path

import pytest

from election_night.bundle import OPENING_2026, build_night_bundle, write_bundle
from election_night.goldens import AFTER_OPENING_2026
from election_night.mockfeed.scenario import load_scenario
from election_night.name_inputs import load_name_inputs
from election_night.names import ForecastUnmatched
from election_night.payload import build_payload, project
from election_night.projection.count_extension import RaceInputs
from election_night.projection.forecast_weighted import (
    FORECAST_CORRUPT,
    FORECAST_MISSING,
    FORECAST_UNMATCHED,
    resolve_forecast,
)
from election_night.replay.gate_result import model_files, model_version

ROOT = Path(__file__).parent.parent
CITY_2026 = ROOT / "tests" / "fixtures" / "feed" / "city-2026"
NIGHT_BUNDLE = ROOT / "data" / "night-bundle"
TRUSTEE_WARDS = ROOT / "data" / "mock-feed" / "trustee_wards_2026.csv"
PINNED = "backend-2026-10-09.2"


def build(
    inputs=NIGHT_BUNDLE / "inputs", gates=ROOT / "gates", forecast_only=False, root=NIGHT_BUNDLE
):
    return build_night_bundle(
        CITY_2026,
        load_name_inputs(inputs),
        OPENING_2026,
        TRUSTEE_WARDS,
        gates,
        inputs / "advance_turnout_2026.json",
        forecast_only=forecast_only,
        bundle_dir=root,
    )


@pytest.fixture(scope="module")
def bundle():
    return build()


@pytest.fixture
def inputs(tmp_path):
    copy = tmp_path / "night-bundle" / "inputs"
    shutil.copytree(NIGHT_BUNDLE / "inputs", copy)
    return copy


def set_advance(inputs: Path, **fields) -> None:
    path = inputs / "advance_turnout_2026.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**record, **fields}), encoding="utf-8")


def mayor(b) -> dict:
    return next(r for r in b["races"] if r["id"] == "mayor")


def restamped(body: bytes) -> bytes:
    data = json.loads(body)
    data["seq"] = str(AFTER_OPENING_2026)
    return json.dumps(data).encode("utf-8")


def test_building_the_bundle_twice_gives_the_same_bytes(bundle, tmp_path):
    write_bundle(bundle, tmp_path / "first.json")
    write_bundle(build(), tmp_path / "second.json")

    assert (tmp_path / "first.json").read_bytes() == (tmp_path / "second.json").read_bytes()


def test_every_projected_race_has_expected_totals_covering_exactly_its_polls(bundle):
    projected = [r for r in bundle["races"] if r["level"] in ("mayor", "council", "trustee")]

    assert len(projected) == 1 + 25 + 12 + 12
    for race in projected:
        assert RaceInputs.from_bundle(race["expected"]).units == race["polls"], race["id"]
    by_ward = {w.ward: w for w in RaceInputs.from_bundle(mayor(bundle)["expected"]).wards}
    for ward in mayor(bundle)["wards"]:
        inputs = by_ward[ward["num"]]
        assert inputs.election_day_units + len(inputs.aggregates) == ward["polls"]
        assert [a.code for a in inputs.aggregates] == [97, 98, 99]


def test_the_french_boards_have_no_expected_totals(bundle):
    french = [r for r in bundle["races"] if r["level"] == "french_trustee"]

    assert french and all("expected" not in r for r in french)


def test_with_no_2026_advance_figure_the_ladders_fallback_is_used_and_recorded(bundle):
    assert bundle["ward_aggregates"]["path"] == "historical_shares"
    assert bundle["ward_aggregates"]["advance_voters"] is None
    for ward in mayor(bundle)["expected"]["wards"]:
        for agg in ward["aggregates"]:
            assert agg["votes"] is None and 0 < agg["share"] < 1


def test_a_released_citywide_advance_figure_is_split_across_the_wards(inputs):
    source = "https://www.toronto.ca/news/advance-vote-turnout-2026/"
    set_advance(inputs, advance_voters=150_000, published_date="2026-10-13", source_url=source)
    b = build(inputs)

    assert b["ward_aggregates"]["path"] == "citywide"
    assert b["ward_aggregates"]["advance_voters"] == 150_000
    assert b["ward_aggregates"]["source"]["source_url"] == source
    advance = mail = 0.0
    for ward in mayor(b)["expected"]["wards"]:
        for agg in ward["aggregates"]:
            if agg["code"] == 97:
                mail += 1
                assert agg["votes"] is None and 0 < agg["share"] < 1
            else:
                advance += agg["votes"]
    # The mayor's office ratio is 1, so its advance aggregates hold the whole figure.
    assert advance == pytest.approx(150_000)
    assert mail == 25


def test_the_bundle_carries_the_frozen_parameters_fitted_on_every_historical_night(bundle):
    frozen = json.loads((ROOT / "gates" / "params" / "night.json").read_text(encoding="utf-8"))

    assert bundle["projection"]["params"] == frozen
    assert sorted(frozen) == ["council", "mayor", "trustee"]


def test_frozen_parameters_that_differ_from_a_fresh_fit_fail_the_build(tmp_path):
    gates = tmp_path / "gates"
    shutil.copytree(ROOT / "gates", gates)
    path = gates / "params" / "night.json"
    params = json.loads(path.read_text(encoding="utf-8"))
    params["council"]["kappa"] += 1
    path.write_text(json.dumps(params), encoding="utf-8")

    with pytest.raises(ValueError, match="election-night params"):
        build(gates=gates)


def test_the_bundle_holds_for_the_running_model_version(bundle):
    assert bundle["model_version"] == model_version(ROOT, model_files(ROOT))


def test_the_bundle_pins_the_forecast_draws_and_the_payload_carries_their_release_tag(bundle):
    assert bundle["forecast"]["release_tag"] == PINNED
    assert (NIGHT_BUNDLE / bundle["forecast"]["npz"]).is_file()
    assert bundle["forecast_release_tag"] == PINNED
    body = json.loads(build_payload(*_city_2026(), resolve_forecast(bundle, NIGHT_BUNDLE)))
    assert body["forecast_release_tag"] == PINNED


def test_an_image_bundle_reads_the_test_files_as_before_results(bundle):
    body = json.loads(build_payload(*_city_2026(), resolve_forecast(bundle, NIGHT_BUNDLE)))

    assert body["state"] == "before_results"


def _city_2026():
    return (
        (CITY_2026 / "unofficialresult.json").read_bytes(),
        (CITY_2026 / "unofficialresult-wardbyward.json").read_bytes(),
    )


@pytest.fixture(scope="module")
def counting():
    """A mid-count Mock Feed snapshot, restamped after the opening time."""
    scenario = load_scenario(seed=1)
    return tuple(restamped(b) for b in scenario.count_snapshot(scenario.steps // 2))


def _variant(bundle: dict, root: Path, counting) -> dict:
    """The mayor's variant at a mid-count refresh, from the bundle as resolved at pipeline
    start, ungated so the variant shows whatever the gates say."""
    resolved = resolve_forecast({k: v for k, v in bundle.items() if k != "gates"}, root)
    body, _ = project(*counting, resolved)
    return mayor(body)["projection"]["variant"]


def test_the_pinned_forecast_resolves_and_weights_the_mayors_draws(bundle, counting):
    variant = _variant(bundle, NIGHT_BUNDLE, counting)

    assert variant["off_reason"] in (None, "low_ess")
    assert variant["ess"] is not None


def test_missing_draws_turn_the_variant_off_without_failing_the_pipeline(
    bundle, counting, tmp_path
):
    variant = _variant(bundle, tmp_path, counting)

    assert variant == {"in_effect": "count_only", "ess": None, "off_reason": FORECAST_MISSING}


def test_corrupt_draws_turn_the_variant_off_without_failing_the_pipeline(
    bundle, counting, tmp_path
):
    npz = tmp_path / bundle["forecast"]["npz"]
    npz.parent.mkdir(parents=True)
    data = (NIGHT_BUNDLE / bundle["forecast"]["npz"]).read_bytes()
    npz.write_bytes(data[: len(data) // 2])

    assert _variant(bundle, tmp_path, counting)["off_reason"] == FORECAST_CORRUPT


def test_unmatched_draws_turn_the_variant_off_without_failing_the_pipeline(bundle, counting):
    unmatched = {
        **bundle,
        "races": [
            {**r, "candidates": [{**c, "candidate_id": None} for c in r["candidates"]]}
            for r in bundle["races"]
        ],
    }

    assert _variant(unmatched, NIGHT_BUNDLE, counting)["off_reason"] == FORECAST_UNMATCHED


def _unmatch_forecast(inputs: Path) -> None:
    path = inputs / "mayoral_forecast.json"
    forecast = json.loads(path.read_text(encoding="utf-8"))
    forecast["election_day"]["pairwise_margin"]["challenger_candidate_id"] = "per_nobody"
    path.write_text(json.dumps(forecast), encoding="utf-8")


def test_an_unmatched_forecast_fails_the_freeze_build(inputs):
    _unmatch_forecast(inputs)

    with pytest.raises(ForecastUnmatched):
        build(inputs, root=inputs.parent)


def test_an_unmatched_forecast_on_a_forecast_only_rebuild_turns_the_variant_off(inputs, counting):
    _unmatch_forecast(inputs)
    b = build(inputs, forecast_only=True, root=inputs.parent)

    assert "per_nobody" not in {c["candidate_id"] for c in mayor(b)["candidates"]}
    assert _variant(b, inputs.parent, counting)["off_reason"] == FORECAST_UNMATCHED


def test_a_released_advance_figure_without_its_source_fails_the_build(inputs):
    set_advance(inputs, advance_voters=150_000)

    with pytest.raises(ValueError, match="source_url"):
        build(inputs)
