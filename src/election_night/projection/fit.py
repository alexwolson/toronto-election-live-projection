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
"""

import numpy as np

from election_night.projection.count_extension import Params
from election_night.replay.historical import Night

FLOOR = 1e-4  # the smallest 1/(concentration + 1) a fit may return


def _concentration(excess: float, spread: float) -> float:
    inverse = max(excess / spread, FLOOR)
    return 1 / inverse - 1


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
            sizes = ed.sum(axis=1)
            if sizes.sum() <= 0:
                continue
            p = ed.sum(axis=0) / sizes.sum()
            p_spread = float((p * (1 - p)).sum())
            counted = ed[sizes > 0]
            n = sizes[sizes > 0][:, None]
            x = counted / n
            unit_excess += float(((x - p) ** 2 - p * (1 - p) / n).sum())
            unit_spread += p_spread * len(counted)
            if len(sizes) > 1 and sizes.mean() > 0:
                cvs.append(sizes.std() / sizes.mean())
            agg = race.votes[is_agg].sum(axis=0).astype(float)
            if agg.sum() > 0:
                q = agg / agg.sum()
                agg_excess += float(((q - p) ** 2 - p * (1 - p) / agg.sum()).sum())
                agg_spread += p_spread
    if not cvs or unit_spread <= 0 or agg_spread <= 0:
        raise ValueError("no races to fit")
    return Params(
        kappa=_concentration(unit_excess, unit_spread),
        size_cv=float(np.sqrt(np.mean(np.square(cvs)))),
        omega=_concentration(agg_excess, agg_spread),
    )
