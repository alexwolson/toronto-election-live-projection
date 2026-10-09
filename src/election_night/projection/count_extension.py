"""The count-extension projection for a single-unit race (#17 § Election-Night Projection, #33).

The projected result is the counted votes plus a simulated Outstanding Vote. The feed gives a
race's counted votes and Reporting Progress, but not which units are in, so every refresh scores
each combination of the race's Ward Aggregates being in or out (8 per City ward; across several
wards, how many of each code are in), crossed with a grid of citywide turnout levels, against the
race's own count. Reporting Progress is never used
to scale anything: it only says how many units are in.

Under a combination and a turnout level the race's expected total is each City ward's `base`
(electors x its historical turnout ratio x the office's votes per mayoral vote) times the level.
Advance aggregates have a known expected size; mail aggregates a share of the ward's total; the
rest is spread over the election-day units. The count is scored by a Gaussian on its total.

Each draw then takes a (combination, level) from that posterior and simulates:
- the outstanding election-day votes, split by a Dirichlet around the counted shares whose
  concentration comes from the fitted unit-to-unit spread and the units out and in;
- the outstanding aggregates, split by one direction-free early-vote shift per race, a Dirichlet
  around the counted shares shared by advance and mail.

Pure numpy and seeded by the caller: no sampler, nothing read from the clock or the night.
"""

import math
from dataclasses import dataclass
from itertools import product

import numpy as np

DRAWS = 10_000
# Citywide mayoral turnout, uniform, as mayoral votes over the pre-night electors list (before
# election-day additions), which runs a few points above the City's reported turnout. Toronto's
# 2003-2023 elections reported 29.7%-54.7%; the approved 0.20-0.60 left out 2014, which is 0.604
# on this basis, so the top was raised to 0.70 (Alex, 2026-10-08), before any replay was scored
# (#33, ADR 0030).
TURNOUT_GRID = np.round(np.arange(0.20, 0.70 + 1e-9, 0.005), 3)
PSEUDO_VOTES = 0.5  # per candidate, so a candidate at 0 keeps a proper Dirichlet
BAND = (5.0, 50.0, 95.0)  # the central 90% range and its middle tick
MIN_CONCENTRATION = 1e-3
# Combinations are counts per code: 216 for the largest 2026 areas (five City wards, three codes).
# Beyond this many a race fails closed rather than slow the tick.
MAX_COMBINATIONS = 4096


@dataclass(frozen=True)
class Params:
    """A level's frozen parameters, fitted on the historical files (projection.fit)."""

    kappa: float  # Dirichlet concentration of an election-day unit's shares around its race's
    size_cv: float  # coefficient of variation of election-day unit sizes within a race
    omega: float  # Dirichlet concentration of the Ward Aggregates' shares around election day


@dataclass(frozen=True)
class Aggregate:
    """One Ward Aggregate: an advance one with an expected size in votes, or a mail one with an
    expected share of its ward's total."""

    code: int
    votes: float | None
    share: float | None
    spread: float  # relative standard deviation of its size


@dataclass(frozen=True)
class WardInputs:
    ward: str
    base: float  # the race's expected votes in this City ward per unit of citywide turnout
    election_day_units: int
    aggregates: tuple[Aggregate, ...]


@dataclass(frozen=True)
class RaceInputs:
    wards: tuple[WardInputs, ...]

    @property
    def units(self) -> int:
        return sum(w.election_day_units + len(w.aggregates) for w in self.wards)

    @classmethod
    def from_bundle(cls, expected: dict) -> RaceInputs:
        """From a bundle race's `expected` entry."""
        return cls(
            tuple(
                WardInputs(
                    w["ward"],
                    w["base"],
                    w["election_day_units"],
                    tuple(Aggregate(**a) for a in w["aggregates"]),
                )
                for w in expected["wards"]
            )
        )


@dataclass(frozen=True)
class _Hypotheses:
    """Every (combination, turnout level) the count allows, with its posterior weight."""

    codes: tuple[int, ...]
    counts: np.ndarray  # (H, codes): how many of each code's aggregates are in
    weights: np.ndarray  # (H,)
    k: np.ndarray  # (H,) election-day units in
    mu: np.ndarray  # (H,) mean election-day unit size
    out_mean: np.ndarray  # (H,) expected votes in the aggregates still out
    out_var: np.ndarray  # (H,) and their variance


def _hypotheses(
    inputs: RaceInputs, params: Params, received: int, counted: float
) -> _Hypotheses | None:
    """Score every combination of how many of each code's aggregates are in, crossed with every
    turnout level, against the race's own count.

    A code's aggregates across the race's City wards are exchangeable: a combination is a count
    per code, weighted by its number of subsets so the prior stays flat over subsets. Their sum
    takes the code's mean size, plus the exact variance of a random subset of its wards' sizes
    and each aggregate's own spread. For a one-ward race this is every subset, 8 for 97/98/99.
    """
    level = TURNOUT_GRID
    groups: dict[int, list[tuple[WardInputs, Aggregate]]] = {}
    for w in inputs.wards:
        for a in w.aggregates:
            groups.setdefault(a.code, []).append((w, a))
    codes = tuple(sorted(groups))
    m = np.array([len(groups[c]) for c in codes], dtype=int)
    if np.prod(m + 1) > MAX_COMBINATIONS:
        return None
    n_ed = sum(w.election_day_units for w in inputs.wards)

    # Each code's sizes at each turnout level: mean, variance across wards, and own spread.
    size_mean, size_var, own_var = (np.zeros((len(level), len(codes))) for _ in range(3))
    for g, code in enumerate(codes):
        sizes = np.array(
            [
                np.full(level.shape, a.votes) if a.votes is not None else a.share * w.base * level
                for w, a in groups[code]
            ]
        )  # (wards, L)
        spread = np.array([a.spread for _, a in groups[code]])[:, None]
        size_mean[:, g] = sizes.mean(axis=0)
        size_var[:, g] = sizes.var(axis=0)
        own_var[:, g] = ((spread * sizes) ** 2).mean(axis=0)
    total = sum(w.base for w in inputs.wards) * level
    election_day = total - (size_mean * m).sum(axis=1)
    mean_unit = election_day / max(n_ed, 1)

    counts = np.array(list(product(*(range(n + 1) for n in m))), dtype=int).reshape(
        int(np.prod(m + 1)), len(codes)
    )
    # Each count's number of subsets: a flat prior over which aggregates are in.
    prior_by_count = np.array(
        [sum(math.log(math.comb(n, c)) for n, c in zip(m, row)) for row in counts]
    )
    c_idx, l_idx = np.meshgrid(np.arange(len(counts)), np.arange(len(level)), indexing="ij")
    c_idx, l_idx = c_idx.ravel(), l_idx.ravel()
    i = counts[c_idx]  # (H, codes)
    out = m - i
    # Variance of the sum of a random subset of i of a code's m sizes.
    subset = np.where(m > 1, i * out / np.maximum(m - 1, 1), 0.0) * size_var[l_idx]
    k = received - i.sum(axis=1)
    mu = mean_unit[l_idx]
    mean = k * mu + (i * size_mean[l_idx]).sum(axis=1)
    var = (
        np.maximum(k, 0) * (params.size_cv * mu) ** 2
        + (subset + i * own_var[l_idx]).sum(axis=1)
        + 1.0
    )
    prior = prior_by_count[c_idx]
    valid = (k >= 0) & (k <= n_ed) & (election_day[l_idx] > 0)
    log_w = np.where(valid, prior - 0.5 * (counted - mean) ** 2 / var - 0.5 * np.log(var), -np.inf)
    if not np.isfinite(log_w).any():
        return None
    weights = np.exp(log_w - log_w.max())
    return _Hypotheses(
        codes=codes,
        counts=i,
        weights=weights / weights.sum(),
        k=k,
        mu=mu,
        out_mean=(out * size_mean[l_idx]).sum(axis=1),
        out_var=(subset + out * own_var[l_idx]).sum(axis=1),
    )


def aggregate_posterior(
    inputs: RaceInputs, params: Params, received: int, counted: float
) -> dict[tuple, float]:
    """The posterior probability of each combination, as ((code, aggregates in), ...)."""
    found = _hypotheses(inputs, params, received, counted)
    if found is None:
        return {}
    posterior: dict[tuple, float] = {}
    for row, weight in zip(found.counts, found.weights):
        key = tuple((code, int(n)) for code, n in zip(found.codes, row))
        posterior[key] = posterior.get(key, 0.0) + float(weight)
    return posterior


def _dirichlet(rng: np.random.Generator, concentration: np.ndarray, centre: np.ndarray):
    """One Dirichlet draw per row: concentration (D,) around centre, (K,) or one per row."""
    centre = np.broadcast_to(centre, (len(concentration), centre.shape[-1]))
    gammas = rng.gamma(np.maximum(concentration, MIN_CONCENTRATION)[:, None] * centre)
    sums = gammas.sum(axis=1, keepdims=True)
    # A row whose gammas all underflow falls back to its centre.
    return np.where(sums > 0, gammas / np.where(sums > 0, sums, 1.0), centre)


def draw_final_shares(
    inputs: RaceInputs,
    params: Params,
    votes: np.ndarray,
    received: int,
    rng: np.random.Generator,
    draws: int = DRAWS,
) -> np.ndarray | None:
    """Draws of every candidate's final share in points, (draws, candidates), or None when the
    race shows no projection: nothing in, everything in, or no hypothesis fits its count."""
    votes = np.asarray(votes, dtype=float)
    if received <= 0 or received >= inputs.units or votes.sum() <= 0:
        return None
    counted = votes.sum()
    found = _hypotheses(inputs, params, received, counted)
    if found is None:
        return None
    n_ed = sum(w.election_day_units for w in inputs.wards)
    pick = rng.choice(len(found.weights), size=draws, p=found.weights)
    k, mu = found.k[pick], found.mu[pick]
    out = n_ed - k
    sd = params.size_cv * mu * np.sqrt(out)
    ed_votes = np.maximum(0.0, out * mu + sd * rng.standard_normal(draws))
    agg_sd = np.sqrt(found.out_var[pick])
    agg_votes = np.maximum(0.0, found.out_mean[pick] + agg_sd * rng.standard_normal(draws))

    # The counted shares estimate the race's shares with an error both outstanding parts share:
    # from the units counted, or, with only aggregates in, from the early-vote shift. Each draw
    # takes one race centre, then splits the election-day and aggregate votes around it.
    counted_shares = (votes + PSEUDO_VOTES) / (counted + PSEUDO_VOTES * len(votes))
    effective = 1 + params.size_cv**2
    centre_variance = np.where(
        k >= 1, 1 / ((params.kappa + 1) * np.maximum(k, 1) / effective), 1 / (params.omega + 1)
    )
    centre = _dirichlet(rng, 1 / centre_variance - 1, counted_shares)
    ed_concentration = (params.kappa + 1) * np.maximum(out, 1) / effective - 1
    ed_split = _dirichlet(rng, ed_concentration, centre)
    agg_split = _dirichlet(rng, np.full(draws, params.omega), centre)

    final = votes[None, :] + ed_votes[:, None] * ed_split + agg_votes[:, None] * agg_split
    return 100 * final / final.sum(axis=1, keepdims=True)


def bands(draws: np.ndarray, keys: tuple[str, ...]) -> dict[str, dict[str, float]]:
    """Each candidate's central 90% final-share range and middle tick, in points to 2 dp."""
    low, mid, high = np.percentile(draws, BAND, axis=0)
    return {
        key: {"low": round(float(lo), 2), "mid": round(float(mi), 2), "high": round(float(hi), 2)}
        for key, lo, mi, hi in zip(keys, low, mid, high)
    }
