"""The mayor's forecast-weighted variant (#17 § Mayor's forecast-weighted variant; #41).

The count-only draws, each weighted by the final Mayoral Forecast's density at that draw (S2):
a Gaussian KDE over the forecast's signed leader-minus-challenger margin draws, in points of the
full ballot, with Silverman's rule-of-thumb bandwidth, 0.9 min(sd, IQR/1.34) n^(-1/5) (Silverman
1986, eq. 3.31; Alex, 2026-10-09), evaluated exactly in log space at each count-only draw's own
final margin between that pair. The pair is the forecast's own top two by win probability.

Below a Kish effective sample size of 1,000 of the 10,000 draws, that refresh falls back to
count-only, with no hysteresis. The variant is off all night if the pinned draws are missing or
corrupt, or can't be matched to the bundle's mayoral rows, which `resolve_forecast` decides once
at pipeline start.
"""

import hashlib
import math
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from election_night.feed import MAYOR_OFFICE_ID
from election_night.gates import forecast_pair
from election_night.projection.count_extension import bands

ESS_MIN = 1_000.0  # `forecast_weighted_variant.ess_fallback.threshold`
SUM_TOLERANCE = 1e-6  # a draw's named shares plus the residual pool sum to 1
CHUNK = 500  # count-only draws per block of the exact KDE, to bound memory

# Why the variant is off at a refresh; null while it is in effect.
FORECAST_MISSING = "forecast_missing"
FORECAST_CORRUPT = "forecast_corrupt"
FORECAST_UNMATCHED = "forecast_unmatched"
LOW_ESS = "low_ess"


def silverman_bandwidth(values: np.ndarray) -> float:
    """0.9 min(sd, IQR/1.34) n^(-1/5); the sd alone when the IQR is 0 (R's bw.nrd0)."""
    values = np.asarray(values, dtype=float)
    sd = float(np.std(values, ddof=1))
    q1, q3 = np.percentile(values, [25, 75])
    spread = min(sd, (q3 - q1) / 1.34) or sd
    return 0.9 * spread * values.size ** (-0.2)


@dataclass(frozen=True, eq=False)
class ForecastDensity:
    """The forecast's margin density, with its pair as the bundle's Ballot Names."""

    leader: str  # the leader's Ballot Name
    challenger: str
    margins: np.ndarray  # the forecast's leader-minus-challenger margin draws, in points
    bandwidth: float

    def log_density(self, x: np.ndarray) -> np.ndarray:
        """The KDE's log density at each of `x`, exactly, by log-sum-exp over every draw."""
        x = np.asarray(x, dtype=float)
        h = self.bandwidth
        norm = math.log(self.margins.size * h * math.sqrt(2 * math.pi))
        out = np.empty(x.size)
        for start in range(0, x.size, CHUNK):
            z = (x[start : start + CHUNK, None] - self.margins[None, :]) / h
            e = -0.5 * z * z
            top = e.max(axis=1, keepdims=True)
            out[start : start + CHUNK] = top[:, 0] + np.log(np.exp(e - top).sum(axis=1)) - norm
        return out

    def shifted(self, points: float) -> ForecastDensity:
        """The density with every margin draw moved by `points`, bandwidth kept (S3)."""
        return ForecastDensity(self.leader, self.challenger, self.margins + points, self.bandwidth)


def weigh(
    density: ForecastDensity, keys: tuple[str, ...], shares: np.ndarray
) -> tuple[np.ndarray, float] | None:
    """Each draw's normalised weight and the weights' Kish ESS, or None when the forecast's
    pair is not among the race's candidates."""
    if density.leader not in keys or density.challenger not in keys:
        return None
    margins = shares[:, keys.index(density.leader)] - shares[:, keys.index(density.challenger)]
    log_w = density.log_density(margins)
    weights = np.exp(log_w - log_w.max())
    weights /= weights.sum()
    return weights, kish_ess(weights)


def kish_ess(weights: np.ndarray) -> float:
    return float(weights.sum() ** 2 / (weights**2).sum())


def weighted_bands(
    shares: np.ndarray, weights: np.ndarray, keys: tuple[str, ...]
) -> dict[str, dict[str, float]]:
    """Each candidate's weighted central 90% final-share range and middle tick."""
    return bands(shares, keys, weights)


def _read_draws(path: Path, digest: str) -> tuple[list[str], np.ndarray] | None:
    """The asset's ids and named shares, or None unless it is whole and coherent."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if hashlib.sha256(data).hexdigest() != digest:
        return None
    try:
        with np.load(path, allow_pickle=False) as arrays:
            ids = [str(c) for c in arrays["candidate_ids"]]
            full = np.asarray(arrays["full_ballot"], dtype=float)
            pool = np.asarray(arrays["residual_pool"], dtype=float)
    except OSError, KeyError, ValueError, EOFError, zipfile.BadZipFile:
        return None
    if full.ndim != 2 or full.shape != (pool.size, len(ids)) or len(ids) < 2 or pool.size < 2:
        return None
    if not (np.isfinite(full).all() and np.isfinite(pool).all()):
        return None
    if np.abs(full.sum(axis=1) + pool - 1).max() > SUM_TOLERANCE:
        return None
    return ids, full


def resolve_forecast(bundle: dict, root: Path) -> dict:
    """The bundle, at pipeline start, with its pinned forecast resolved once for the night:
    `forecast_density` when the draws are whole and their pair sits on exactly one mayoral row
    each, else `forecast_off` with the reason. `bundle["forecast"]` points at the draws asset,
    `{"release_tag", "npz", "npz_sha256"}`, with `npz` relative to `root`."""
    resolved = {k: v for k, v in bundle.items() if k not in ("forecast_density", "forecast_off")}
    pointer = bundle.get("forecast")
    if not pointer:
        return {**resolved, "forecast_off": FORECAST_MISSING}
    path = Path(root) / pointer["npz"]
    if not path.exists():
        return {**resolved, "forecast_off": FORECAST_MISSING}
    found = _read_draws(path, pointer["npz_sha256"])
    if found is None:
        return {**resolved, "forecast_off": FORECAST_CORRUPT}
    ids, full = found
    leader, challenger = forecast_pair(full)
    mayor = next((r for r in bundle["races"] if r["office_id"] == MAYOR_OFFICE_ID), None)
    rows = mayor["candidates"] if mayor else []
    names = []
    for i in (leader, challenger):
        matched = [r["key"] for r in rows if r.get("candidate_id") == ids[i]]
        if len(matched) != 1:
            return {**resolved, "forecast_off": FORECAST_UNMATCHED}
        names.append(matched[0])
    margins = 100.0 * (full[:, leader] - full[:, challenger])
    bandwidth = silverman_bandwidth(margins)
    if not (math.isfinite(bandwidth) and bandwidth > 0):
        # Every draw at one margin has no density to weight by.
        return {**resolved, "forecast_off": FORECAST_CORRUPT}
    density = ForecastDensity(names[0], names[1], margins, bandwidth)
    return {**resolved, "forecast_density": density}
