"""Gated projections in the payload (#45; ADR 0002).

A level shows its projection only while its Gate Result passed, or Alex approved it, for the
running model version. Otherwise the whole level shows the tally, and the payload says why. The
mayor follows the ladder: the forecast-weighted variant, else count-only, else the tally; and
below the variant's ESS floor no Estimated Range shows at all (ADR 0002).
"""

import json

import numpy as np
import pytest

from election_night.gates import load_preregistration
from election_night.payload import project
from election_night.projection.forecast_weighted import ForecastDensity, silverman_bandwidth
from election_night.projection.history import replay_bundle
from election_night.replay.historical import YEARS, load_night
from election_night.replay.orders import arrival_order
from election_night.replay.run import PREREGISTRATION
from election_night.replay.snapshots import snapshots

PREREG = load_preregistration(PREREGISTRATION)
VERSION = "model-v"


@pytest.fixture(scope="module")
def nights():
    return {year: load_night(year, PREREG) for year in YEARS}


def midnight(nights, year):
    night = nights[year]
    order = arrival_order(night, PREREG, "interleaved", 0)
    (snap,) = snapshots(night, order, steps=[len(order) // 2])
    return snap, {**replay_bundle(night, nights, PREREG), "model_version": VERSION}


@pytest.fixture(scope="module")
def council_2022(nights):
    return midnight(nights, 2022)


@pytest.fixture(scope="module")
def mayor_2023(nights):
    snap, bundle = midnight(nights, 2023)
    margins = np.random.default_rng(2).normal(10, 30, 4_000)  # broad: the variant stays in effect
    density = ForecastDensity("Chow Olivia", "Bailão Ana", margins, silverman_bandwidth(margins))
    return snap, {**bundle, "forecast_density": density}


def gates(**levels) -> dict:
    """Gate records: `level=(passed, model_version)` or `level=(passed, model_version, approved)`."""
    records = {}
    for name, record in levels.items():
        passed, version, *approved = record
        records[name.replace("_", "-")] = {
            "pass": passed,
            "model_version": version,
            "approved": bool(approved and approved[0]),
        }
    return records


def run(snap, bundle, records):
    gated = {**bundle, "gates": records} if records is not None else bundle
    body, _ = project(snap.all_office, snap.ward_by_ward, gated)
    return body


def races(body, level):
    return [r for r in body["races"] if r["level"] == level and r["state"] == "counting"]


def test_without_gate_records_the_projections_stand_ungated_as_in_the_replays(council_2022):
    body = run(*council_2022, None)

    assert body["levels"]["council"]["projection"] == "ungated"
    assert all(r["projection"] for r in races(body, "council"))


def test_a_passed_gate_for_the_running_version_puts_the_level_live(council_2022):
    body = run(*council_2022, gates(council=(True, VERSION)))

    assert body["levels"]["council"]["projection"] == "live"
    for race in races(body, "council"):
        assert race["projection"]["shown"] == "count_only"
        assert "count_only" in race["projection"]["bands"]


@pytest.mark.parametrize(
    "record, status",
    [
        ((False, VERSION), "gate_failed"),
        ((True, "another-version"), "version_mismatch"),
        (None, "gate_missing"),
    ],
)
def test_a_level_not_live_shows_the_tally_and_says_why(council_2022, record, status):
    records = gates(council=record) if record else gates(trustee=(True, VERSION))
    body = run(*council_2022, records)

    assert body["levels"]["council"]["projection"] == status
    assert all(r["projection"] is None for r in races(body, "council"))
    assert all(r["candidates"][0]["votes"] is not None for r in races(body, "council"))


def test_the_mayor_approved_shows_the_forecast_weighted_range_and_never_count_only(mayor_2023):
    body = run(
        *mayor_2023,
        gates(
            mayor_count_only=(False, VERSION),
            mayor_forecast_weighted=(False, VERSION, True),
        ),
    )
    (mayor,) = races(body, "mayor")

    assert body["levels"]["mayor"] == {
        "projection": "live",
        "variant": "live",
        "approved": True,
    }
    assert mayor["projection"]["shown"] == "forecast_weighted"
    assert list(mayor["projection"]["bands"]) == ["forecast_weighted"]


def test_below_the_ess_floor_the_approved_mayor_shows_no_estimated_range(mayor_2023):
    snap, bundle = mayor_2023
    # A tight forecast far from every draw collapses the weights below the ESS floor.
    far = np.full(4_000, 95.0) + np.random.default_rng(3).normal(0, 0.1, 4_000)
    bundle = {**bundle, "forecast_density": ForecastDensity("Chow Olivia", "Bailão Ana", far, 0.05)}
    body = run(
        snap,
        bundle,
        gates(
            mayor_count_only=(False, VERSION),
            mayor_forecast_weighted=(False, VERSION, True),
        ),
    )
    (mayor,) = races(body, "mayor")

    assert mayor["projection"]["variant"]["off_reason"] == "low_ess"
    assert mayor["projection"]["shown"] is None
    assert mayor["projection"]["bands"] == {}


def test_the_mayor_falls_to_count_only_when_only_count_only_passed(mayor_2023):
    body = run(
        *mayor_2023,
        gates(mayor_count_only=(True, VERSION), mayor_forecast_weighted=(False, VERSION)),
    )
    (mayor,) = races(body, "mayor")

    assert body["levels"]["mayor"] == {
        "projection": "live",
        "variant": "gate_failed",
        "approved": False,
    }
    assert mayor["projection"]["shown"] == "count_only"
    assert list(mayor["projection"]["bands"]) == ["count_only"]


def test_the_mayor_shows_the_tally_when_neither_version_is_live(mayor_2023):
    body = run(
        *mayor_2023,
        gates(mayor_count_only=(False, VERSION), mayor_forecast_weighted=(False, VERSION)),
    )
    (mayor,) = races(body, "mayor")

    assert body["levels"]["mayor"]["projection"] == "gate_failed"
    assert mayor["projection"] is None


def test_an_approval_holds_only_for_the_version_it_names(mayor_2023):
    body = run(
        *mayor_2023,
        gates(
            mayor_count_only=(False, VERSION),
            mayor_forecast_weighted=(False, "another-version", True),
        ),
    )

    assert body["levels"]["mayor"]["projection"] == "version_mismatch"
    assert races(body, "mayor")[0]["projection"] is None


def test_gating_keeps_the_payload_deterministic(council_2022):
    records = gates(council=(True, VERSION))
    first = json.dumps(run(*council_2022, records))
    assert first == json.dumps(run(*council_2022, records))


def test_a_level_not_live_publishes_no_bands_at_all_not_even_stub_ones(council_2022):
    # A council race the bundle can't model (no expected totals) falls back to stub bands; on a
    # gated night whose council gate failed, the whole level shows the tally (#17).
    snap, bundle = council_2022
    bundle = json.loads(json.dumps(bundle))
    spec = next(r for r in bundle["races"] if r["id"] == "councillor-1")
    del spec["expected"]
    body = run(snap, bundle, gates(council=(False, VERSION)))

    assert next(r for r in body["races"] if r["id"] == "councillor-1")["projection"] is None
    assert all(r["projection"] is None for r in races(body, "council"))
