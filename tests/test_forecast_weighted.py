"""The mayor's forecast-weighted variant, at the payload function (#41).

The count-only draws are weighted by the final Mayoral Forecast's density at each draw's own
final leader-minus-challenger margin (S2). Below a Kish ESS of 1,000 the refresh falls back to
count-only. A forecast that is missing, corrupt or unmatched turns the variant off.
"""

import hashlib
import json

import numpy as np
import pytest

from election_night.gates import load_preregistration
from election_night.payload import build_payload, project
from election_night.projection.forecast_weighted import resolve_forecast
from election_night.projection.history import replay_bundle
from election_night.replay.historical import YEARS, load_night
from election_night.replay.orders import arrival_order
from election_night.replay.run import PREREGISTRATION
from election_night.replay.snapshots import snapshots

PREREG = load_preregistration(PREREGISTRATION)
CHOW, BAILAO = "per_chow", "per_bailao"


@pytest.fixture(scope="module")
def replay_2023():
    nights = {year: load_night(year, PREREG) for year in YEARS}
    night = nights[2023]
    bundle = replay_bundle(night, nights, PREREG)
    order = arrival_order(night, PREREG, "interleaved", 0)
    (snap,) = snapshots(night, order, steps=[len(order) // 2])
    # Name the forecast's pair on the bundle's mayoral rows, as the 2026 build does.
    mayor = next(r for r in bundle["races"] if r["id"] == "mayor")
    for row in mayor["candidates"]:
        row["candidate_id"] = {"Chow Olivia": CHOW, "Bailão Ana": BAILAO}.get(row["key"])
    return snap, bundle


@pytest.fixture(scope="module")
def count_only(replay_2023):
    """The count-only payload and draws, with no forecast in the bundle."""
    snap, bundle = replay_2023
    return project(snap.all_office, snap.ward_by_ward, bundle)


def margin_draws(count_only) -> np.ndarray:
    """Chow minus Bailão in each count-only draw, in points."""
    keys, shares, _ = count_only[1]["mayor"]["count_only"]
    return shares[:, keys.index("Chow Olivia")] - shares[:, keys.index("Bailão Ana")]


def write_forecast(tmp_path, margins, ids=(CHOW, BAILAO)) -> dict:
    """A forecast's draws whose leader-minus-challenger margin is `margins` points, as the
    Backend's draws asset holds them, and the bundle's pointer to them."""
    margins = np.asarray(margins, dtype=float)
    full = np.column_stack([0.45 + margins / 200, 0.45 - margins / 200])
    path = tmp_path / "draws.npz"
    np.savez(
        path,
        candidate_ids=np.array(ids),
        full_ballot=full,
        residual_pool=1 - full.sum(axis=1),
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"release_tag": "backend-test", "npz": "draws.npz", "npz_sha256": digest}


def with_forecast(bundle, tmp_path, pointer) -> dict:
    return resolve_forecast({**bundle, "forecast": pointer}, tmp_path)


def mayor(body) -> dict:
    return next(r for r in body["races"] if r["id"] == "mayor")


def test_both_bands_come_from_the_same_draws_and_the_weights_pull_toward_the_forecast(
    replay_2023, count_only, tmp_path
):
    snap, bundle = replay_2023
    observed = margin_draws(count_only)
    # A forecast centred two count-only standard deviations above the count's median margin.
    centre = np.median(observed) + 2 * observed.std()
    rng = np.random.default_rng(3)
    pointer = write_forecast(tmp_path, rng.normal(centre, observed.std(), 16_000))
    body, draws = project(
        snap.all_office, snap.ward_by_ward, with_forecast(bundle, tmp_path, pointer)
    )

    race = mayor(body)
    co_keys, co_shares, co_weights = draws["mayor"]["count_only"]
    fw_keys, fw_shares, fw_weights = draws["mayor"]["forecast_weighted"]
    assert co_weights is None
    assert fw_keys == co_keys
    assert np.array_equal(fw_shares, co_shares)  # the same draws, reweighted
    assert np.array_equal(co_shares, count_only[1]["mayor"]["count_only"][1])
    assert fw_weights.shape == (10_000,) and abs(fw_weights.sum() - 1) < 1e-9
    assert (
        race["projection"]["bands"]["count_only"]
        == mayor(count_only[0])["projection"]["bands"]["count_only"]
    )
    bands = race["projection"]["bands"]
    assert list(bands["forecast_weighted"]) == list(bands["count_only"])
    assert (
        bands["forecast_weighted"]["Chow Olivia"]["mid"] > bands["count_only"]["Chow Olivia"]["mid"]
    )
    variant = race["projection"]["variant"]
    assert variant["in_effect"] == "forecast_weighted"
    assert variant["off_reason"] is None
    assert 1_000 <= variant["ess"] < 10_000


def test_below_an_ess_of_1000_the_refresh_falls_back_to_count_only(
    replay_2023, count_only, tmp_path
):
    snap, bundle = replay_2023
    observed = margin_draws(count_only)
    # A tight forecast far outside the count's draws puts nearly all the weight on a few.
    far = observed.max() + 5.0
    pointer = write_forecast(tmp_path, np.random.default_rng(4).normal(far, 0.2, 16_000))
    body, _ = project(snap.all_office, snap.ward_by_ward, with_forecast(bundle, tmp_path, pointer))

    variant = mayor(body)["projection"]["variant"]
    assert variant["in_effect"] == "count_only"
    assert variant["off_reason"] == "low_ess"
    assert variant["ess"] < 1_000
    # Both bands are still carried, so the route and the Replays see what was set aside.
    assert "forecast_weighted" in mayor(body)["projection"]["bands"]


def corrupt_draws(tmp_path, pointer, how):
    path = tmp_path / pointer["npz"]
    if how == "truncated":
        path.write_bytes(path.read_bytes()[:-100])
    elif how == "nan":
        with np.load(path) as arrays:
            full = arrays["full_ballot"].copy()
            ids, pool = arrays["candidate_ids"], arrays["residual_pool"]
        full[7, 0] = np.nan
        np.savez(path, candidate_ids=ids, full_ballot=full, residual_pool=pool)
        pointer = {**pointer, "npz_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    elif how == "sums":
        with np.load(path) as arrays:
            ids, full = arrays["candidate_ids"], arrays["full_ballot"]
        np.savez(path, candidate_ids=ids, full_ballot=full, residual_pool=np.zeros(len(full)))
        pointer = {**pointer, "npz_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return pointer


@pytest.mark.parametrize(
    "case, reason",
    [
        ("no pointer", "forecast_missing"),
        ("no file", "forecast_missing"),
        ("truncated", "forecast_corrupt"),
        ("nan", "forecast_corrupt"),
        ("sums", "forecast_corrupt"),
        ("degenerate", "forecast_corrupt"),
        ("unknown id", "forecast_unmatched"),
        ("id on two rows", "forecast_unmatched"),
    ],
)
def test_missing_corrupt_or_unmatched_draws_turn_the_variant_off(
    replay_2023, count_only, tmp_path, case, reason
):
    snap, bundle = replay_2023
    margins = np.random.default_rng(5).normal(10, 8, 16_000)
    if case == "degenerate":  # every draw the same margin: no bandwidth, no density
        margins = np.full(16_000, 10.0)
    ids = (CHOW, "per_nobody") if case == "unknown id" else (CHOW, BAILAO)
    pointer = write_forecast(tmp_path, margins, ids)
    bundle = json.loads(json.dumps(bundle))
    if case == "no pointer":
        pointer = None
    elif case == "no file":
        (tmp_path / pointer["npz"]).unlink()
    elif case == "id on two rows":
        rows = mayor(bundle)["candidates"]
        next(r for r in rows if r["candidate_id"] is None)["candidate_id"] = CHOW
    elif case in ("truncated", "nan", "sums"):
        pointer = corrupt_draws(tmp_path, pointer, case)
    resolved = with_forecast(bundle, tmp_path, pointer)
    body, draws = project(snap.all_office, snap.ward_by_ward, resolved)

    race = mayor(body)
    assert resolved["forecast_off"] == reason
    assert race["projection"]["variant"] == {
        "in_effect": "count_only",
        "ess": None,
        "off_reason": reason,
    }
    assert list(race["projection"]["bands"]) == ["count_only"]
    assert set(draws["mayor"]) == {"count_only"}
    # Count-only goes on unchanged.
    assert race["projection"]["bands"] == {
        "count_only": mayor(count_only[0])["projection"]["bands"]["count_only"]
    }


def test_an_unresolved_bundle_has_the_variant_off_as_missing(count_only):
    variant = mayor(count_only[0])["projection"]["variant"]
    assert variant == {"in_effect": "count_only", "ess": None, "off_reason": "forecast_missing"}


def test_the_same_pair_and_forecast_give_the_same_bytes(replay_2023, tmp_path):
    snap, bundle = replay_2023
    pointer = write_forecast(tmp_path, np.random.default_rng(6).normal(10, 8, 16_000))
    first = build_payload(
        snap.all_office, snap.ward_by_ward, with_forecast(bundle, tmp_path, pointer)
    )
    second = build_payload(
        snap.all_office, snap.ward_by_ward, with_forecast(bundle, tmp_path, pointer)
    )
    assert first == second
    assert '"forecast_weighted"' in first.decode()
