"""The Replay scorer (`gates/preregistration.json` § checkpoints, baseline, scores, pass_criteria).

A case is one race at one checkpoint of one arrival order: the projection's draws of every
candidate's final share, the Live Tally's shares, and the certified final shares, all in points.
The eventual winner and runner-up come from the final count. The Tally Baseline is the tally read
as a point mass, its leader winning for certain.

Cases are averaged within a race, races within a night, and nights equally. G1 and G2 pool every
case of a night into one rate, and the per-night rates are averaged with nights weighted equally.
For each candidate's share, G2 first takes each case's share of candidates covered.

A case's draws may carry weights (the forecast-weighted variant: the count-only draws
reweighted, #41). Every score then reads the weighted empirical distribution: CRPS exactly, win
probabilities as weighted shares of draws led, and central ranges from the inverse of the
weighted CDF.
"""

from dataclasses import dataclass

import numpy as np

from election_night.names import name_words


@dataclass(frozen=True, eq=False)
class Case:
    night: int
    race: str  # the payload's race id
    checkpoint: str  # "50%", or a real capture's name
    order: str | None  # "early-0"; None for a real capture
    draws: np.ndarray  # (draws, candidates): final shares
    tally: np.ndarray  # (candidates,): counted shares
    final: np.ndarray  # (candidates,): certified shares
    retired: bool = False  # all units in: the projection has retired and the count stands
    keys: tuple[str, ...] = ()  # the candidates' Ballot Names, in the draws' order
    weights: np.ndarray | None = None  # (draws,): each draw's weight, summing to 1; None: equal
    # Which version of the race the draws are: count_only; for the forecast-weighted variant's
    # Replays also forecast_weighted, stress_test (the shifted forecast) and tally (#41).
    variant: str = "count_only"


@dataclass(frozen=True)
class CaseScore:
    night: int
    race: str
    retired: bool
    margin_crps: float
    baseline_margin_error: float
    brier: float
    baseline_brier: float
    share_crps: float  # diagnostic only
    g1_calls: int  # candidates given at least the confidence
    g1_hits: int  # of those, the ones who won
    g2_margin: bool  # the margin's central range holds the final margin
    g2_shares: int  # candidates whose central range holds their final share
    candidates: int


def crps(draws: np.ndarray, observed: float, weights: np.ndarray | None = None) -> float:
    """Exact CRPS of an empirical forecast (the Backend's `empirical_crps`), equally weighted
    or with `weights` summing to 1: E|X - y| - E|X - X'| / 2."""
    values = np.asarray(draws, dtype=float)
    n = values.size
    if n == 0 or not np.all(np.isfinite(values)):
        raise ValueError("draws must be non-empty and finite")
    if weights is None:
        values = np.sort(values)
        absolute_error = float(np.mean(np.abs(values - observed)))
        dispersion = float(np.sum((2 * np.arange(n) - n + 1) * values))
        return max(0.0, absolute_error - dispersion / (n * n))
    order = np.argsort(values, kind="stable")
    values, w = values[order], np.asarray(weights, dtype=float)[order]
    absolute_error = float(np.sum(w * np.abs(values - observed)))
    below = np.cumsum(w) - w  # the weight of the draws sorted before each
    above = 1.0 - below - w
    dispersion = float(np.sum(w * values * (below - above)))
    return max(0.0, absolute_error - dispersion)


def _first_max(rows: np.ndarray) -> np.ndarray:
    """Each row's top candidate; ties go to the earlier one."""
    return np.argmax(rows, axis=-1)


def _brier(probabilities: np.ndarray, winner: int) -> float:
    outcome = np.zeros_like(probabilities)
    outcome[winner] = 1.0
    return float(np.sum((probabilities - outcome) ** 2))


def _within(draws: np.ndarray, value, interval_mass: float, weights=None):
    tail = (1 - interval_mass) / 2
    if weights is None:
        low, high = np.quantile(draws, [tail, 1 - tail], axis=0)
    else:
        low, high = (
            np.quantile(draws, q, axis=0, weights=weights, method="inverted_cdf")
            for q in (tail, 1 - tail)
        )
    return (low <= value) & (value <= high)


def win_probabilities(draws: np.ndarray, weights: np.ndarray | None = None) -> np.ndarray:
    """Each candidate's share of draws led (ties to the earlier), weighted if given."""
    k = draws.shape[1]
    if weights is None:
        return np.bincount(_first_max(draws), minlength=k) / draws.shape[0]
    return np.bincount(_first_max(draws), weights=weights, minlength=k) / weights.sum()


def score_case(case: Case, confidence: float, interval_mass: float) -> CaseScore:
    draws, tally, final, w = case.draws, case.tally, case.final, case.weights
    k = final.size
    if draws.ndim != 2 or draws.shape[1] != k or tally.size != k:
        raise ValueError(f"{case.race}: draws, tally and final name different candidates")
    winner, runner_up = (int(i) for i in np.argsort(-final, kind="stable")[:2])
    final_margin = float(final[winner] - final[runner_up])
    margins = draws[:, winner] - draws[:, runner_up]
    tally_margin = float(tally[winner] - tally[runner_up])

    probabilities = win_probabilities(draws, w)
    baseline = np.zeros(k)
    baseline[_first_max(tally)] = 1.0
    calls = probabilities >= confidence

    return CaseScore(
        night=case.night,
        race=case.race,
        retired=case.retired,
        margin_crps=crps(margins, final_margin, w),
        baseline_margin_error=abs(tally_margin - final_margin),
        brier=_brier(probabilities, winner),
        baseline_brier=_brier(baseline, winner),
        share_crps=float(np.mean([crps(draws[:, c], final[c], w) for c in range(k)])),
        g1_calls=int(calls.sum()),
        g1_hits=int(calls[winner]),
        g2_margin=bool(_within(margins, final_margin, interval_mass, w)),
        g2_shares=int(_within(draws, final, interval_mass, w).sum()),
        candidates=k,
    )


MEANS = ("margin_crps", "baseline_margin_error", "brier", "baseline_brier", "share_crps")


def night_scores(scores: list[CaseScore]) -> dict[int, dict]:
    """Per night: the race-weighted means, and G1 and G2 pooled over the night's cases."""
    nights = {}
    for night in sorted({s.night for s in scores}):
        cases = [s for s in scores if s.night == night]
        races = {}
        for s in cases:
            races.setdefault(s.race, []).append(s)
        summary = {
            name: float(np.mean([np.mean([getattr(s, name) for s in r]) for r in races.values()]))
            for name in MEANS
        }
        calls = sum(s.g1_calls for s in cases)
        summary["g1"] = sum(s.g1_hits for s in cases) / calls if calls else None
        summary["g2_margin"] = sum(s.g2_margin for s in cases) / len(cases)
        # Each case's share of candidates covered, so a crowded race weighs as one case (#29).
        summary["g2_shares"] = float(np.mean([s.g2_shares / s.candidates for s in cases]))
        summary |= {"races": len(races), "cases": len(cases), "g1_calls": calls}
        summary["retired_cases"] = sum(s.retired for s in cases)
        nights[night] = summary
    return nights


def totals(nights: dict[int, dict]) -> dict:
    """Nights weighted equally; a night with no G1 call is left out of G1."""
    total = {name: float(np.mean([n[name] for n in nights.values()])) for name in MEANS}
    g1 = [n["g1"] for n in nights.values() if n["g1"] is not None]
    total["g1"] = float(np.mean(g1)) if g1 else None
    for name in ("g2_margin", "g2_shares"):
        total[name] = float(np.mean([n[name] for n in nights.values()]))
    return total


def criteria(nights: dict[int, dict], prereg: dict, level: str) -> list[dict]:
    """Criteria 1-5 with their values and pre-registered thresholds. `level` is the prereg's
    level name (mayor, council, trustee). A G1 with no call anywhere is null and doesn't fail."""
    listed = {c["id"]: c for c in prereg["pass_criteria"]["criteria"]}
    total = totals(nights)
    beat = sum(n["margin_crps"] < n["baseline_margin_error"] for n in nights.values())
    c2, c4, c5 = listed[2], listed[4], listed[5]
    g2 = {"margin": total["g2_margin"], "shares": total["g2_shares"]}
    results = [
        (1, total["margin_crps"] < total["baseline_margin_error"], total["margin_crps"],
         total["baseline_margin_error"]),
        (2, beat >= c2["min_nights"][level], beat, c2["min_nights"][level]),
        (3, total["brier"] <= total["baseline_brier"], total["brier"], total["baseline_brier"]),
        (4, total["g1"] is None or total["g1"] >= c4["min_hit_rate"], total["g1"],
         c4["min_hit_rate"]),
        (5, all(v >= c5["min_coverage"] for v in g2.values()), g2, c5["min_coverage"]),
    ]  # fmt: skip
    return [
        {"id": i, "name": listed[i]["name"], "pass": bool(ok), "value": value, "threshold": bar}
        for i, ok, value, bar in results
    ]


BAILAO_NIGHT = 2023


def bailao_check(cases: list[Case], prereg: dict, candidate: str) -> dict:
    """The Bailão check: at the 2023 ward-by-ward capture, `candidate`'s win probability (the
    share of draws she leads) is under the pre-registered maximum. `candidate` is her name as
    the forecast writes it, matched to the Ballot Names by their words. Without that case the
    check fails closed, with a null value."""
    listed = next(c for c in prereg["pass_criteria"]["criteria"] if c["id"] == 6)
    capture = next(e for e in prereg["real_captures"]["mayor"] if e["night"] == BAILAO_NIGHT)
    checkpoint = f"capture {capture['time_edt']}"
    value = None
    for case in cases:
        if case.night == BAILAO_NIGHT and case.race == "mayor" and case.checkpoint == checkpoint:
            (index,) = [
                i for i, k in enumerate(case.keys) if name_words(k) == name_words(candidate)
            ]
            value = float(win_probabilities(case.draws, case.weights)[index])
    bar = listed["max_win_probability"]
    return {
        "id": 6,
        "name": listed["name"],
        "pass": value is not None and value < bar,
        "value": value,
        "threshold": bar,
    }


def checkpoint_steps(received: np.ndarray, units: int, percents) -> list[tuple[int, int]]:
    """Each percent's checkpoint: the first step whose Reporting Progress is at or above it.
    `received[step]` is the race's Reporting Units in after that step. Two percents may share a
    step; a percent the race never reaches has no checkpoint."""
    scaled = np.asarray(received) * 100
    grid = []
    for p in percents:
        step = int(np.searchsorted(scaled, p * units, side="left"))
        if step < scaled.size:
            grid.append((p, step))
    return grid
