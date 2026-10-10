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
class MayorParams:
    """The mayor's frozen parameters (projection.fit.fit_mayor). Its units are City wards."""

    kappa: float  # Dirichlet concentration of an election-day unit's shares around its ward's
    size_cv: float  # coefficient of variation of election-day unit sizes within a ward
    tau: float  # Dirichlet concentration of a ward's election-day shares around the city's
    omega_city: float  # of the citywide Ward Aggregates' shares around citywide election day
    omega_ward: float  # of a ward's aggregates' shares around its election day, after the shift
    # The effective number of nights omega_city was fitted on. Each draw takes its own shift
    # spread from that estimate's uncertainty (scaled-inverse-chi-squared); infinite: known.
    omega_city_nu: float = math.inf


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

    @property
    def top_total(self) -> float:
        """The race's expected total at the top of the turnout grid: no count above it fits."""
        return sum(w.base for w in self.wards) * float(TURNOUT_GRID[-1])

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
class _Grid:
    """Every (combination, turnout level) for one set of City wards, scored against a count.
    Arrays are (combinations, levels)."""

    codes: tuple[int, ...]
    counts: np.ndarray  # (C, codes): how many of each code's aggregates are in
    log_w: np.ndarray  # unnormalised log posterior; -inf where the count rules it out
    k: np.ndarray  # election-day units in
    mu: np.ndarray  # mean election-day unit size
    out_mean: np.ndarray  # expected votes in the aggregates still out
    out_var: np.ndarray  # and their variance


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


def _grid(
    inputs: RaceInputs, params: Params | MayorParams, received: int, counted: float
) -> _Grid | None:
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
    prior = np.array([sum(math.log(math.comb(n, c)) for n, c in zip(m, row)) for row in counts])
    i = counts[:, None, :]  # (C, 1, codes)
    out = m - i
    # Variance of the sum of a random subset of i of a code's m sizes.
    subset = np.where(m > 1, i * out / np.maximum(m - 1, 1), 0.0) * size_var[None]
    k = np.broadcast_to(received - counts.sum(axis=1)[:, None], (len(counts), len(level)))
    mu = np.broadcast_to(mean_unit[None, :], k.shape)
    mean = k * mu + (i * size_mean[None]).sum(axis=2)
    var = (
        np.maximum(k, 0) * (params.size_cv * mu) ** 2
        + (subset + i * own_var[None]).sum(axis=2)
        + 1.0
    )
    valid = (k >= 0) & (k <= n_ed) & (election_day[None, :] > 0)
    log_w = np.where(
        valid, prior[:, None] - 0.5 * (counted - mean) ** 2 / var - 0.5 * np.log(var), -np.inf
    )
    return _Grid(
        codes=codes,
        counts=counts,
        log_w=log_w,
        k=k,
        mu=mu,
        out_mean=(out * size_mean[None]).sum(axis=2),
        out_var=(subset + out * own_var[None]).sum(axis=2),
    )


def _hypotheses(
    inputs: RaceInputs, params: Params, received: int, counted: float
) -> _Hypotheses | None:
    """The race's grid as one posterior over (combination, turnout level)."""
    grid = _grid(inputs, params, received, counted)
    if grid is None or not np.isfinite(grid.log_w).any():
        return None
    log_w = grid.log_w.ravel()
    weights = np.exp(log_w - log_w.max())
    return _Hypotheses(
        codes=grid.codes,
        counts=np.repeat(grid.counts, len(TURNOUT_GRID), axis=0),
        weights=weights / weights.sum(),
        k=grid.k.ravel(),
        mu=grid.mu.ravel(),
        out_mean=grid.out_mean.ravel(),
        out_var=grid.out_var.ravel(),
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


def _shifted(centre: np.ndarray, shift: np.ndarray) -> np.ndarray:
    """Each row's centre times its shift, renormalised. A row whose shift has no mass where its
    centre has any keeps its centre."""
    early = centre * shift
    total = early.sum(axis=1, keepdims=True)
    return np.where(total > 0, early / np.where(total > 0, total, 1.0), centre)


def _shift_concentration(params: MayorParams, rng: np.random.Generator, draws: int):
    """Each draw's concentration of the citywide early-vote shift. Its spread v = 1/(omega + 1)
    is estimated from a few nights, so each draw takes v from the scaled-inverse-chi-squared
    distribution with the fit's effective nights as degrees of freedom, centred on the fit."""
    if math.isinf(params.omega_city_nu):
        return np.full(draws, params.omega_city)
    nu = params.omega_city_nu
    v = nu / (params.omega_city + 1) / rng.chisquare(nu, size=draws)
    return 1 / np.minimum(v, 1 - MIN_CONCENTRATION) - 1


def mayor_final_votes(
    inputs: RaceInputs,
    params: MayorParams,
    votes: np.ndarray,
    received: np.ndarray,
    rng: np.random.Generator,
    draws: int = DRAWS,
    per_ward: bool = False,
) -> tuple[np.ndarray, list[np.ndarray] | None] | None:
    """Draws of every candidate's final citywide votes, (draws, candidates), summed over City
    wards, and with `per_ward` each ward's own (in `inputs` order). None when the race shows no
    projection: nothing in, everything in, or no hypothesis fits its count.

    `votes` is (wards, candidates) and `received` each ward's Reporting Units in, both in
    `inputs` order. Each ward is sized as a one-ward race (#33), but the turnout level is
    citywide: its posterior is the product of every ward's, and each ward's combination is drawn
    given the draw's level. Each draw then takes one early-vote shift per candidate, applied in
    every ward, with ward-level noise around it. A ward with no election-day unit counted in a
    draw is centred on the citywide counted shares, with the between-ward spread.
    """
    votes = np.asarray(votes, dtype=float)
    received = np.asarray(received)
    units = np.array([w.election_day_units + len(w.aggregates) for w in inputs.wards])
    if received.sum() <= 0 or (received >= units).all() or votes.sum() <= 0:
        return None
    grids = []
    for w, n, v in zip(inputs.wards, received, votes):
        grid = _grid(RaceInputs((w,)), params, int(n), float(v.sum()))
        if grid is None or not np.isfinite(grid.log_w).any():
            return None
        grids.append(grid)

    # The citywide turnout level: each ward's likelihood summed over its combinations.
    by_level = [np.logaddexp.reduce(g.log_w, axis=0) for g in grids]
    log_level = np.sum(by_level, axis=0)
    if not np.isfinite(log_level).any():
        return None
    level_p = np.exp(log_level - log_level.max())
    level = rng.choice(len(TURNOUT_GRID), size=draws, p=level_p / level_p.sum())

    candidates = votes.shape[1]
    city_counted = votes.sum(axis=0)
    city_shares = (city_counted + PSEUDO_VOTES) / (city_counted.sum() + PSEUDO_VOTES * candidates)
    shift = _dirichlet(rng, _shift_concentration(params, rng, draws), city_shares) / city_shares
    effective = 1 + params.size_cv**2

    city = np.zeros((draws, candidates))
    wards = [] if per_ward else None
    for w, n, v, grid, ward_level in zip(inputs.wards, received, votes, grids, by_level):
        if n >= w.election_day_units + len(w.aggregates):
            final = np.broadcast_to(v, (draws, candidates))
        else:
            # The ward's combination given each draw's level.
            seen = np.isfinite(ward_level)[None, :]
            log_c = np.where(seen, grid.log_w - np.where(seen, ward_level, 0.0), -np.inf)
            cumulative = np.cumsum(np.exp(log_c), axis=0).T[level]  # (draws, C)
            # Scaled by each row's own total, so round-off never picks a combination of weight 0.
            u = rng.random(draws)[:, None] * cumulative[:, -1:]
            pick = (u >= cumulative).sum(axis=1)
            k, mu = grid.k[pick, level], grid.mu[pick, level]
            out = w.election_day_units - k
            ed_votes = np.maximum(
                0.0, out * mu + params.size_cv * mu * np.sqrt(out) * rng.standard_normal(draws)
            )
            agg_sd = np.sqrt(grid.out_var[pick, level])
            agg_votes = np.maximum(
                0.0, grid.out_mean[pick, level] + agg_sd * rng.standard_normal(draws)
            )

            counted = (v + PSEUDO_VOTES) / (v.sum() + PSEUDO_VOTES * candidates)
            own = k >= 1
            concentration = np.where(
                own, (params.kappa + 1) * np.maximum(k, 1) / effective - 1, params.tau
            )
            centre = _dirichlet(rng, concentration, np.where(own[:, None], counted, city_shares))
            ed_concentration = (params.kappa + 1) * np.maximum(out, 1) / effective - 1
            ed_split = _dirichlet(rng, ed_concentration, centre)
            agg_split = _dirichlet(rng, np.full(draws, params.omega_ward), _shifted(centre, shift))
            final = v[None, :] + ed_votes[:, None] * ed_split + agg_votes[:, None] * agg_split
        city += final
        if wards is not None:
            wards.append(np.array(final))
    return city, wards


def draw_mayor_final_shares(
    inputs: RaceInputs,
    params: MayorParams,
    votes: np.ndarray,
    received: np.ndarray,
    rng: np.random.Generator,
    draws: int = DRAWS,
) -> np.ndarray | None:
    """Draws of every candidate's final citywide share in points, (draws, candidates)."""
    found = mayor_final_votes(inputs, params, votes, received, rng, draws)
    if found is None:
        return None
    city, _ = found
    return 100 * city / city.sum(axis=1, keepdims=True)


def bands(
    draws: np.ndarray, keys: tuple[str, ...], weights: np.ndarray | None = None
) -> dict[str, dict[str, float]]:
    """Each candidate's central 90% final-share range and middle tick, in points to 2 dp. With
    `weights`, the inverse of the weighted empirical CDF."""
    if weights is None:
        low, mid, high = np.percentile(draws, BAND, axis=0)
    else:
        low, mid, high = np.quantile(
            draws, np.array(BAND) / 100, axis=0, weights=weights, method="inverted_cdf"
        )
    return {
        key: {"low": round(float(lo), 2), "mid": round(float(mi), 2), "high": round(float(hi), 2)}
        for key, lo, mi, hi in zip(keys, low, mid, high)
    }
