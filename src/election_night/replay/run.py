"""Replays scored end to end: Count Snapshots -> the payload function -> the scorer (#29).

For every arrival order, each scored race is checked at the first Count Snapshot at or after each
pre-registered point of its own Reporting Progress. The payload function runs on that pair exactly
as on the night, and its own draws for the level's variant are scored. A race whose projection has
retired (all units in) is scored as its tally, which is then exact. Acclaimed races are not scored.

The real captures enter as named checkpoints, pooled with the orders' checkpoints, for each race
of the level the captured file holds with Reporting Progress from 5% up to but not including 100%,
the grid's own range.

The timing-pattern orders and the captures decide criteria 1-5. The stress orders, and the results
without 2014 and without 2023, are reported only.
"""

from dataclasses import dataclass

import numpy as np

from election_night import payload
from election_night.feed import COUNCILLOR_OFFICE_ID, MAYOR_OFFICE_ID
from election_night.gates import ROOT, sha256
from election_night.replay.captures import Capture
from election_night.replay.historical import Night, Race
from election_night.replay.scoring import (
    Case,
    checkpoint_steps,
    criteria,
    night_scores,
    score_case,
    totals,
)
from election_night.replay.snapshots import night_bundle, snapshots

PREREGISTRATION = ROOT / "gates" / "preregistration.json"


@dataclass(frozen=True)
class Level:
    name: str  # the pre-registration's level: mayor, council or trustee
    variant: str  # the payload's projection variant
    offices: tuple[int, ...]

    def reads(self, capture: Capture) -> bool:
        """Whether the capture's real file is the one this level's races are read from."""
        return (capture.file == "ward-by-ward") == (MAYOR_OFFICE_ID in self.offices)


# One Gate Result each (`gate_result.per`).
LEVELS = {
    "council": Level("council", "count_only", (COUNCILLOR_OFFICE_ID,)),
    "trustee": Level("trustee", "count_only", (3, 4)),
    "mayor-count-only": Level("mayor", "count_only", (MAYOR_OFFICE_ID,)),
    "mayor-forecast-weighted": Level("mayor", "forecast_weighted", (MAYOR_OFFICE_ID,)),
}


def _bundle(night: Night, model_version: str) -> dict:
    return {**night_bundle(night), "model_version": model_version}


def _scored(night: Night, bundle: dict, level: Level) -> list[tuple[dict, Race]]:
    """The level's races that are not acclaimed, with their certified counts."""
    races = {(r.office_id, r.num): r for r in night.races}
    return [
        (spec, races[(spec["office_id"], spec["num"])])
        for spec in bundle["races"]
        if spec["office_id"] in level.offices and not spec["acclaimed"]
    ]


def _case(night, race: Race, row: dict, draws, level, checkpoint, order) -> Case:
    if row["state"] not in ("counting", "all_units_in"):
        raise ValueError(f"{night.year} {row['id']} at {checkpoint}: state {row['state']}")
    keys = tuple(c["key"] for c in row["candidates"])
    votes = np.array([c["votes"] for c in row["candidates"]], dtype=float)
    tally = 100 * votes / votes.sum() if votes.sum() else np.zeros_like(votes)
    certified = dict(zip(race.candidates, race.certified.tolist()))
    if not set(certified) <= set(keys) or any(
        c["votes"] for c in row["candidates"] if c["key"] not in certified
    ):
        raise ValueError(f"{row['id']}: the payload and the certified count name different people")
    # A name the certified count leaves out (2022 Ward 23's Cynthia Lai, at 0) finishes at 0.
    final = np.array([certified.get(k, 0) for k in keys], dtype=float)
    final = 100 * final / final.sum()
    if row["id"] in draws:
        draw_keys, shares = draws[row["id"]][level.variant]
        if draw_keys != keys:
            raise ValueError(f"{row['id']}: draws and payload name different candidates")
    else:
        shares = tally[None, :]  # the projection has retired: the count stands
    retired = row["id"] not in draws
    return Case(night.year, row["id"], checkpoint, order, shares, tally, final, retired)


def order_cases(
    night: Night,
    order: np.ndarray,
    label: str,
    level: Level,
    prereg: dict,
    model_version: str,
    project=payload.project,
) -> list[Case]:
    """Every scored race of the level at each of its checkpoints along one arrival order."""
    bundle = _bundle(night, model_version)
    percents = prereg["checkpoints"]["reporting_progress_percent"]
    keys = [night.units[i].key for i in order]
    at_step: dict[int, list] = {}
    for spec, race in _scored(night, bundle, level):
        units = set(race.units)
        received = np.concatenate([[0], np.cumsum([k in units for k in keys])])
        for p, step in checkpoint_steps(received, len(race.units), percents):
            at_step.setdefault(step, []).append((spec["id"], race, f"{p}%"))
    cases = []
    for snap in snapshots(night, order, steps=sorted(at_step)):
        body, draws = project(snap.all_office, snap.ward_by_ward, bundle)
        rows = {r["id"]: r for r in body["races"]}
        for race_id, race, checkpoint in at_step[snap.step]:
            cases.append(_case(night, race, rows[race_id], draws, level, checkpoint, label))
    return cases


def capture_cases(
    night: Night,
    capture: Capture,
    level: Level,
    prereg: dict,
    model_version: str,
    project=payload.project,
) -> list[Case]:
    """The level's races the captured file holds, from the grid's lowest point of Reporting
    Progress up to but not including 100%."""
    if not level.reads(capture):
        return []
    lowest = min(prereg["checkpoints"]["reporting_progress_percent"])
    bundle = _bundle(night, model_version)
    body, draws = project(capture.all_office, capture.ward_by_ward, bundle)
    rows = {r["id"]: r for r in body["races"]}
    cases = []
    for spec, race in _scored(night, bundle, level):
        progress = rows[spec["id"]]["progress"]
        if (
            progress
            and progress["received"] * 100 >= lowest * progress["total"]
            and (progress["received"] < progress["total"])
        ):
            row = rows[spec["id"]]
            label = f"capture {capture.time_edt}"
            cases.append(_case(night, race, row, draws, level, label, None))
    return cases


def _summary(cases: list[Case], prereg: dict) -> dict:
    confidence = next(c for c in prereg["pass_criteria"]["criteria"] if c["id"] == 4)
    mass = next(c for c in prereg["pass_criteria"]["criteria"] if c["id"] == 5)
    scores = [score_case(c, confidence["confidence"], mass["interval_mass"]) for c in cases]
    return night_scores(scores)


def _report(nights: dict[int, dict], cases: int) -> dict:
    return {
        "total": totals(nights),
        "nights": {str(y): n for y, n in nights.items()},
        "cases": cases,
    }


def replay_level(
    level_name: str,
    prereg: dict,
    nights: dict[int, Night],
    orders: dict[int, list[tuple[str, int, np.ndarray]]],
    captures: list[Capture],
    model_version: str,
    smoke: bool = False,
    project=payload.project,
) -> dict:
    """The level's Gate Result, without its run number."""
    level = LEVELS[level_name]
    patterns = set(prereg["arrival_orders"]["ward_aggregates"]["timing_patterns"])
    deciding, stress = [], []
    for year, night in nights.items():
        for kind, index, order in orders[year]:
            cases = order_cases(
                night, order, f"{kind}-{index}", level, prereg, model_version, project
            )
            (deciding if kind in patterns else stress).extend(cases)
    for capture in captures:
        if capture.night in nights:
            deciding += capture_cases(
                nights[capture.night], capture, level, prereg, model_version, project
            )

    by_night = _summary(deciding, prereg)
    checks = criteria(by_night, prereg, level.name)
    reported = {}
    for year in (2014, 2023):
        rest = {y: n for y, n in by_night.items() if y != year}
        if year in by_night and rest:
            reported[f"without_{year}"] = _report(rest, sum(n["cases"] for n in rest.values()))
    if stress:
        reported["stress_orders"] = _report(_summary(stress, prereg), len(stress))
    kinds = [kind for year in orders for kind, _, _ in orders[year]]
    per_night = max(1, len(nights))
    return {
        "level": level_name,
        "variant": level.variant,
        "smoke": smoke,
        "pass": all(c["pass"] for c in checks),
        "criteria": checks,
        "scores": _report(by_night, len(deciding)),
        "nights": sorted(nights),
        "cases": len(deciding),
        "orders_per_night": {
            "timing_patterns": sum(k in patterns for k in kinds) // per_night,
            "stress": sum(k not in patterns for k in kinds) // per_night,
        },
        "real_captures": [
            f"{c.night} {c.time_edt} {c.file}"
            for c in captures
            if c.night in nights and level.reads(c)
        ],
        "reported": reported,
        "model_version": model_version,
        "preregistration_sha256": sha256(PREREGISTRATION),
        "forecast_release_tag": None,
    }


def run_replay(level_name: str, prereg: dict, years: list[int], smoke: bool) -> tuple[dict, dict]:
    """Load the nights, draw the orders and replay the level. A smoke run takes the first order
    of each timing pattern and no stress orders. Returns the Gate Result and timing figures."""
    import time

    from election_night.replay.captures import real_captures
    from election_night.replay.gate_result import model_files, model_version
    from election_night.replay.historical import load_night
    from election_night.replay.orders import arrival_order, orders

    start = time.monotonic()
    nights = {year: load_night(year, prereg) for year in years}
    patterns = list(prereg["arrival_orders"]["ward_aggregates"]["timing_patterns"])
    if smoke:
        drawn = {
            y: [(kind, 0, arrival_order(n, prereg, kind, 0)) for kind in patterns]
            for y, n in nights.items()
        }
    else:
        drawn = {y: orders(n, prereg) for y, n in nights.items()}
    listed = prereg["real_captures"]
    kept = {
        key: [e for e in listed[key] if e["night"] in nights]
        for key in ("council_and_trustee", "mayor")
    }
    captures = real_captures({"real_captures": kept}, ROOT, nights)
    loaded = time.monotonic()
    version = model_version(ROOT, model_files(ROOT))
    result = replay_level(level_name, prereg, nights, drawn, captures, version, smoke=smoke)
    done = time.monotonic()
    arrival = prereg["arrival_orders"]
    full_orders = arrival["orders_per_night"] + sum(
        k["orders_per_night"] for k in arrival["stress_orders"]["kinds"].values()
    )
    level_years = prereg["nights"][LEVELS[level_name].name]["years"]
    ran = sum(len(o) for o in drawn.values())
    timing = {
        "load_seconds": loaded - start,
        "replay_seconds": done - loaded,
        "orders": ran,
        "seconds_per_order": (done - loaded) / ran,
        "full_orders": full_orders * len(level_years),
    }
    timing["full_replay_seconds_extrapolated"] = timing["seconds_per_order"] * timing["full_orders"]
    return result, timing
