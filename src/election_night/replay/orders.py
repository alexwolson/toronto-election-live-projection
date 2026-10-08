"""Seeded arrival orders, exactly as `gates/preregistration.json` § arrival_orders states them.

An order is one permutation of the night's Reporting Units (indices into `Night.units`), shared
across offices. Every count, seed and code comes from the pre-registration file; only the meaning
of each named kind is code. Each order draws from its own generator,
`SeedSequence(root, spawn_key=(year, kind_index, order_index))`: first the election-day sequence,
then the Ward Aggregate blocks' placement.
"""

import math
import re

import numpy as np

from election_night.replay.historical import Night


def _rng(prereg: dict, year: int, kind: str, index: int) -> np.random.Generator:
    seeds = prereg["arrival_orders"]["seeds"]
    spawn_key = (year, seeds["kinds"].index(kind), index)
    return np.random.default_rng(np.random.SeedSequence(seeds["root"], spawn_key=spawn_key))


def _late_fraction(prereg: dict) -> float:
    rule = prereg["arrival_orders"]["ward_aggregates"]["timing_patterns"]["late"]
    match = re.search(r"after (\d+)% of election-day units", rule)
    if not match:
        raise ValueError(f"unreadable late rule: {rule!r}")
    return int(match[1]) / 100


def _election_day(night: Night, kind: str, rng: np.random.Generator) -> list[int]:
    units = [i for i, u in enumerate(night.units) if not u.ward_aggregate]
    if kind == "ward_clustered":
        wards = sorted({night.units[i].ward for i in units})
        sequence = []
        for ward in rng.permutation(wards):
            sequence += rng.permutation([i for i in units if night.units[i].ward == ward]).tolist()
        return sequence
    shuffled = rng.permutation(units).tolist()
    if kind in ("size_largest_first", "size_smallest_first"):
        mayor = night.mayor
        size = dict(zip(mayor.units, mayor.votes.sum(axis=1).tolist()))
        sign = -1 if kind == "size_largest_first" else 1
        return sorted(shuffled, key=lambda i: sign * size[night.units[i].key])  # stable: ties stay
    return shuffled


def _place(election_day: list[int], blocks: list[int], timing: str, prereg: dict, rng) -> list[int]:
    blocks = rng.permutation(blocks).tolist()
    n = len(election_day)
    if timing == "early":
        return blocks + election_day
    if timing == "interleaved":
        slots = rng.integers(0, n + 1, size=len(blocks))
    elif timing == "late":
        slots = rng.integers(math.ceil(_late_fraction(prereg) * n), n + 1, size=len(blocks))
    else:
        raise ValueError(f"unknown Ward Aggregate timing {timing!r}")
    placed = sorted(zip(slots.tolist(), range(len(blocks))))  # by slot; ties keep the shuffle
    order, j = [], 0
    for slot in range(n + 1):
        while j < len(placed) and placed[j][0] == slot:
            order.append(blocks[placed[j][1]])
            j += 1
        if slot < n:
            order.append(election_day[slot])
    return order


def arrival_order(night: Night, prereg: dict, kind: str, index: int) -> np.ndarray:
    """The `index`th order of `kind` for the night."""
    arrival = prereg["arrival_orders"]
    patterns = arrival["ward_aggregates"]["timing_patterns"]
    if kind in patterns:
        timing = kind
    elif kind in arrival["stress_orders"]["kinds"]:
        timing = arrival["stress_orders"]["ward_aggregate_timing"]
    else:
        raise ValueError(f"unknown order kind {kind!r}")
    rng = _rng(prereg, night.year, kind, index)
    election_day = _election_day(night, kind, rng)
    blocks = [i for i, u in enumerate(night.units) if u.ward_aggregate]
    return np.array(_place(election_day, blocks, timing, prereg, rng), dtype=np.int64)


def orders(night: Night, prereg: dict) -> list[tuple[str, int, np.ndarray]]:
    """Every pre-registered order for the night: the timing patterns, then the stress orders."""
    arrival = prereg["arrival_orders"]
    patterns = list(arrival["ward_aggregates"]["timing_patterns"])
    weights = arrival["ward_aggregates"]["pattern_weights"]
    if sorted(weights) != sorted(patterns) or len(set(weights.values())) != 1:
        raise ValueError("unequal pattern weights would need unequal order counts")
    per_pattern = arrival["orders_per_pattern"]
    if per_pattern * len(patterns) != arrival["orders_per_night"]:
        raise ValueError("orders_per_pattern doesn't add up to orders_per_night")
    counts = [(kind, per_pattern) for kind in patterns]
    counts += [
        (kind, rule["orders_per_night"]) for kind, rule in arrival["stress_orders"]["kinds"].items()
    ]
    return [
        (kind, index, arrival_order(night, prereg, kind, index))
        for kind, n in counts
        for index in range(n)
    ]
