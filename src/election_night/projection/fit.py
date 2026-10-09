"""A level's parameters, by pooled method of moments on the certified per-unit historical results.

Closed form, so a fold refits in milliseconds and nothing needs a sampler. Each estimate pools
every race of the level on the nights it is given; the caller leaves the held-out night out
(ADR 0029).

- `kappa`: an election-day unit's shares are a Dirichlet around its race's election-day shares.
  For a unit of n votes, E[(x - p)^2] = p(1 - p) [1/(kappa + 1) + kappa / ((kappa + 1) n)], so
  1/(kappa + 1) is the pooled excess of the squared deviations over multinomial noise, divided by
  the pooled p(1 - p).
- `size_cv`: the root mean square, over races, of each race's coefficient of variation of its
  election-day unit sizes.
- `omega`: the Ward Aggregates' combined shares are a Dirichlet around the race's election-day
  shares, by the same moment.

The mayor (`fit_mayor`) takes its units in City wards: `kappa` and `size_cv` as above with each
ward as a race; `tau`, a ward's election-day shares around the city's; `omega_city`, the citywide
aggregates' shares around citywide election day; and `omega_ward`, a ward's aggregates' shares
around its election day shifted by the citywide ratio of aggregate to election-day shares. Its
nights are weighted by MAYOR_NIGHT_SHARES, and `omega_city_nu` is the effective number of
nights behind `omega_city`.
"""

import numpy as np

from election_night.projection.count_extension import MayorParams, Params
from election_night.replay.historical import Night

FLOOR = 1e-4  # the smallest 1/(concentration + 1) a fit may return


def _concentration(excess: float, spread: float) -> float:
    inverse = max(excess / spread, FLOOR)
    return 1 / inverse - 1


def _units(ed: np.ndarray) -> tuple[float, float, float | None]:
    """One race's (or ward's) election-day units: their squared share deviations beyond
    multinomial noise, the matching p(1 - p) sum, and the units' size CV (None for one unit)."""
    sizes = ed.sum(axis=1)
    p = ed.sum(axis=0) / sizes.sum()
    counted = ed[sizes > 0]
    n = sizes[sizes > 0][:, None]
    excess = float(((counted / n - p) ** 2 - p * (1 - p) / n).sum())
    cv = sizes.std() / sizes.mean() if len(sizes) > 1 and sizes.mean() > 0 else None
    return excess, float((p * (1 - p)).sum()) * len(counted), cv


def _excess(observed: np.ndarray, centre: np.ndarray, n: float) -> tuple[float, float]:
    """One share vector's squared deviation from its centre beyond multinomial noise over n
    votes, and the centre's p(1 - p): the two sums a concentration is pooled from."""
    spread = centre * (1 - centre)
    return float(((observed - centre) ** 2 - spread / n).sum()), float(spread.sum())


def fit_level(nights: list[Night], offices: tuple[int, ...]) -> Params:
    unit_excess = unit_spread = agg_excess = agg_spread = 0.0
    cvs = []
    for night in nights:
        aggregate = {u.key: u.ward_aggregate for u in night.units}
        for race in night.races:
            if race.office_id not in offices or len(race.candidates) < 2:
                continue
            is_agg = np.array([aggregate[u] for u in race.units])
            ed = race.votes[~is_agg].astype(float)
            if ed.sum() <= 0:
                continue
            excess, spread, cv = _units(ed)
            unit_excess += excess
            unit_spread += spread
            if cv is not None:
                cvs.append(cv)
            agg = race.votes[is_agg].sum(axis=0).astype(float)
            if agg.sum() > 0:
                excess, spread = _excess(agg / agg.sum(), ed.sum(axis=0) / ed.sum(), agg.sum())
                agg_excess += excess
                agg_spread += spread
    if not cvs or unit_spread <= 0 or agg_spread <= 0:
        raise ValueError("no races to fit")
    return Params(
        kappa=_concentration(unit_excess, unit_spread),
        size_cv=float(np.sqrt(np.mean(np.square(cvs)))),
        omega=_concentration(agg_excess, agg_spread),
    )


# A night's share of every mayoral parameter's fit when it is a training night. 2026 is expected to
# resemble 2023 (Alex, 2026-10-09): an assumption, not fitted (docs/adr/0001). The other nights
# split the rest in their pooled proportions. Without 2023, every night keeps its pooled share.
MAYOR_NIGHT_SHARES = {2023: 0.5}


def _shares(sizes: dict[int, float]) -> dict[int, float]:
    """Each night's share of a pooled estimate: its size, or its fixed share where one is set."""
    fixed = {y: MAYOR_NIGHT_SHARES[y] for y in sizes if y in MAYOR_NIGHT_SHARES}
    rest = sum(v for y, v in sizes.items() if y not in fixed)
    if rest <= 0:  # only fixed nights: they share the whole fit
        return {y: fixed[y] / sum(fixed.values()) for y in sizes}
    left = 1 - sum(fixed.values())
    return {y: fixed.get(y, left * v / rest) for y, v in sizes.items()}


def _pooled(per_night: dict[int, tuple[float, float]]) -> tuple[float, float]:
    """The pooled moment v = excess / spread, each night weighted by its share; and the
    effective number of nights behind it (Kish)."""
    nights = {y: pair for y, pair in per_night.items() if pair[1] > 0}
    if not nights:
        raise ValueError("no mayoral races to fit")
    shares = _shares({y: spread for y, (_, spread) in nights.items()})
    v = sum(shares[y] * excess / spread for y, (excess, spread) in nights.items())
    return v, 1 / sum(w * w for w in shares.values())


def fit_mayor(nights: list[Night]) -> MayorParams:
    moments: dict[str, dict[int, tuple[float, float]]] = {
        name: {} for name in ("kappa", "tau", "omega_city", "omega_ward")
    }
    cvs: dict[int, list[float]] = {}

    def add(name: str, year: int, pair: tuple[float, float]) -> None:
        excess, spread = moments[name].get(year, (0.0, 0.0))
        moments[name][year] = (excess + pair[0], spread + pair[1])

    for night in nights:
        race, year = night.mayor, night.year
        aggregate = {u.key: u.ward_aggregate for u in night.units}
        is_agg = np.array([aggregate[u] for u in race.units])
        votes = race.votes.astype(float)
        city_ed, city_agg = votes[~is_agg].sum(axis=0), votes[is_agg].sum(axis=0)
        if city_ed.sum() <= 0 or city_agg.sum() <= 0:
            continue
        p_city, q_city = city_ed / city_ed.sum(), city_agg / city_agg.sum()
        add("omega_city", year, _excess(q_city, p_city, city_agg.sum()))
        # The citywide shift: each candidate's aggregate share over their election-day share.
        ratio = np.where(p_city > 0, q_city / np.where(p_city > 0, p_city, 1.0), 1.0)
        wards = np.array([w for w, _ in race.units])
        for ward in np.unique(wards):
            ed = votes[(wards == ward) & ~is_agg]
            if ed.sum() <= 0:
                continue
            excess, spread, cv = _units(ed)
            add("kappa", year, (excess, spread))
            if cv is not None:
                cvs.setdefault(year, []).append(cv)
            p = ed.sum(axis=0) / ed.sum()
            add("tau", year, _excess(p, p_city, ed.sum()))
            agg = votes[(wards == ward) & is_agg].sum(axis=0)
            if agg.sum() > 0:
                target = p * ratio / (p * ratio).sum()
                add("omega_ward", year, _excess(agg / agg.sum(), target, agg.sum()))
    if not cvs:
        raise ValueError("no mayoral races to fit")
    pooled = {name: _pooled(per_night) for name, per_night in moments.items()}
    cv_shares = _shares({y: float(len(c)) for y, c in cvs.items()})
    size_cv = np.sqrt(sum(cv_shares[y] * np.mean(np.square(c)) for y, c in cvs.items()))
    return MayorParams(
        kappa=_concentration(pooled["kappa"][0], 1.0),
        size_cv=float(size_cv),
        tau=_concentration(pooled["tau"][0], 1.0),
        omega_city=_concentration(pooled["omega_city"][0], 1.0),
        omega_ward=_concentration(pooled["omega_ward"][0], 1.0),
        omega_city_nu=pooled["omega_city"][1],
    )
