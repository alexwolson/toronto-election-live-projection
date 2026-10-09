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
around its election day shifted by the citywide ratio of aggregate to election-day shares.
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


def fit_mayor(nights: list[Night]) -> MayorParams:
    unit_excess = unit_spread = 0.0
    tau_excess = tau_spread = city_excess = city_spread = ward_excess = ward_spread = 0.0
    cvs = []
    for night in nights:
        race = night.mayor
        aggregate = {u.key: u.ward_aggregate for u in night.units}
        is_agg = np.array([aggregate[u] for u in race.units])
        votes = race.votes.astype(float)
        city_ed, city_agg = votes[~is_agg].sum(axis=0), votes[is_agg].sum(axis=0)
        if city_ed.sum() <= 0 or city_agg.sum() <= 0:
            continue
        p_city, q_city = city_ed / city_ed.sum(), city_agg / city_agg.sum()
        excess, spread = _excess(q_city, p_city, city_agg.sum())
        city_excess += excess
        city_spread += spread
        # The citywide shift: each candidate's aggregate share over their election-day share.
        ratio = np.where(p_city > 0, q_city / np.where(p_city > 0, p_city, 1.0), 1.0)
        wards = np.array([w for w, _ in race.units])
        for ward in np.unique(wards):
            ed = votes[(wards == ward) & ~is_agg]
            if ed.sum() <= 0:
                continue
            excess, spread, cv = _units(ed)
            unit_excess += excess
            unit_spread += spread
            if cv is not None:
                cvs.append(cv)
            p = ed.sum(axis=0) / ed.sum()
            excess, spread = _excess(p, p_city, ed.sum())
            tau_excess += excess
            tau_spread += spread
            agg = votes[(wards == ward) & is_agg].sum(axis=0)
            if agg.sum() > 0:
                target = p * ratio / (p * ratio).sum()
                excess, spread = _excess(agg / agg.sum(), target, agg.sum())
                ward_excess += excess
                ward_spread += spread
    if not cvs or min(unit_spread, tau_spread, city_spread, ward_spread) <= 0:
        raise ValueError("no mayoral races to fit")
    return MayorParams(
        kappa=_concentration(unit_excess, unit_spread),
        size_cv=float(np.sqrt(np.mean(np.square(cvs)))),
        tau=_concentration(tau_excess, tau_spread),
        omega_city=_concentration(city_excess, city_spread),
        omega_ward=_concentration(ward_excess, ward_spread),
    )
