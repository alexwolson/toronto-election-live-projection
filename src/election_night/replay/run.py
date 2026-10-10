"""Replays scored end to end: Count Snapshots -> the payload function -> the scorer (#29).

For every arrival order, each scored race is checked at the first Count Snapshot at or after each
pre-registered point of its own Reporting Progress. The payload function runs on that pair exactly
as on the night, and its own draws for the level's variant are scored. A race whose projection has
retired (all units in) is scored as its tally, which is then exact. Acclaimed races are not scored.

The real captures enter as named checkpoints, pooled with the orders' checkpoints, for each race
of the level the captured file holds with Reporting Progress from 5% up to but not including 100%,
the grid's own range.

The timing-pattern orders and the captures decide criteria 1-5, and for mayor criterion 6, the
Bailão check, on the 2023 capture. The stress orders, and the results
without 2014 and without 2023, are reported only.

The mayor's forecast-weighted variant (#41) runs on the same orders and the same draws as
count-only: each refresh's one payload call gives the count-only draws and the variant's weights.
The night's held-out 1-day forecast (S4) is its Night Bundle's forecast. At each refresh the
variant scores its weighted draws when the payload put them in effect; below the ESS floor it
scores count-only's draws if count-only met criteria 1-6 on the same run, else the tally. The
wrong-forecast stress test reweights the same count-only draws by the forecast shifted against
the eventual winner by S3's shift, with the same fallback. The variant passes only if it meets
criteria 1-6, beats count-only on total margin CRPS and on 3 of 4 nights, and meets G1 and
criterion 6 under the stress test.

Each case is scored as soon as its order is replayed, and only its scores are kept, apart from
the real captures' cases, which the Bailão check reads.
"""

import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from functools import partial
from itertools import pairwise

import numpy as np

from election_night import payload
from election_night.feed import COUNCILLOR_OFFICE_ID, MAYOR_OFFICE_ID
from election_night.gates import HOLDOUT_FORECASTS, ROOT, sha256
from election_night.names import name_words
from election_night.projection.forecast_weighted import ESS_MIN, resolve_forecast, weigh
from election_night.replay.captures import Capture
from election_night.replay.historical import Night, Race
from election_night.replay.scoring import (
    BAILAO_NIGHT,
    Case,
    CaseScore,
    bailao_check,
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


def _bundle(night: Night, model_version: str, make_bundle=night_bundle) -> dict:
    return {**make_bundle(night), "model_version": model_version}


def _scored(night: Night, bundle: dict, level: Level) -> list[tuple[dict, Race]]:
    """The level's races that are not acclaimed, with their certified counts."""
    races = {(r.office_id, r.num): r for r in night.races}
    return [
        (spec, races[(spec["office_id"], spec["num"])])
        for spec in bundle["races"]
        if spec["office_id"] in level.offices and not spec["acclaimed"]
    ]


# The versions of each refresh the variant's Replays score.
VARIANT_CASES = ("count_only", "forecast_weighted", "stress_test", "tally")


def _stress_weights(bundle: dict, race: Race, keys, shares, prereg: dict) -> np.ndarray | None:
    """The count-only draws' weights under the forecast shifted against the eventual winner by
    S3's shift, or None below the ESS floor."""
    density = bundle.get("forecast_density")
    if density is None:
        raise ValueError(f"{race.name}: the variant's Replays need the night's forecast")
    winner = race.candidates[int(np.argmax(race.certified))]
    shift = prereg["stress_test_shift"]["shift_points"]
    if winner == density.leader:
        shifted = density.shifted(-shift)
    elif winner == density.challenger:
        shifted = density.shifted(shift)
    else:
        raise ValueError(f"{winner} won, but the forecast's pair is not theirs")
    found = weigh(shifted, keys, shares)
    if found is None:
        raise ValueError("the forecast's pair is not among the payload's candidates")
    weights, ess = found
    return weights if ess >= ESS_MIN else None


def _cases(night, race: Race, row: dict, draws, level, checkpoint, order, bundle, prereg):
    """The race's case at this refresh; for the forecast-weighted variant, one per version in
    `VARIANT_CASES`, leaving out a weighted version below the ESS floor."""
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
    retired = row["id"] not in draws
    # A retired projection scores the count, which then stands, in every version.
    case = Case(
        night.year, row["id"], checkpoint, order, tally[None, :], tally, final, retired, keys
    )
    if retired and level.variant == "count_only":
        return [case]
    if retired:
        return [replace(case, variant=v) for v in VARIANT_CASES]
    draw_keys, shares, weights = draws[row["id"]]["count_only"]
    if draw_keys != keys:
        raise ValueError(f"{row['id']}: draws and payload name different candidates")
    if level.variant == "count_only":
        return [replace(case, draws=shares, weights=weights)]
    cases = [replace(case, draws=shares), replace(case, variant="tally")]
    if row["projection"]["variant"]["in_effect"] == "forecast_weighted":
        _, weighted, weights = draws[row["id"]]["forecast_weighted"]
        cases.append(replace(case, draws=weighted, weights=weights, variant="forecast_weighted"))
    stress = _stress_weights(bundle, race, keys, shares, prereg)
    if stress is not None:
        cases.append(replace(case, draws=shares, weights=stress, variant="stress_test"))
    return cases


def order_cases(
    night: Night,
    order: np.ndarray,
    label: str,
    level: Level,
    prereg: dict,
    model_version: str,
    project=payload.project,
    make_bundle=night_bundle,
) -> list[Case]:
    """Every scored race of the level at each of its checkpoints along one arrival order."""
    bundle = _bundle(night, model_version, make_bundle)
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
        scored = {race_id for race_id, _, _ in at_step[snap.step]}
        body, draws = project(snap.all_office, snap.ward_by_ward, bundle, only=scored)
        rows = {r["id"]: r for r in body["races"]}
        for race_id, race, checkpoint in at_step[snap.step]:
            row = rows[race_id]
            cases += _cases(night, race, row, draws, level, checkpoint, label, bundle, prereg)
    return cases


def capture_cases(
    night: Night,
    capture: Capture,
    level: Level,
    prereg: dict,
    model_version: str,
    project=payload.project,
    make_bundle=night_bundle,
) -> list[Case]:
    """The level's races the captured file holds, from the grid's lowest point of Reporting
    Progress up to but not including 100%."""
    if not level.reads(capture):
        return []
    lowest = min(prereg["checkpoints"]["reporting_progress_percent"])
    bundle = _bundle(night, model_version, make_bundle)
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
            cases += _cases(night, race, row, draws, level, label, None, bundle, prereg)
    return cases


def with_holdout_forecast(bundle: dict, year: int) -> dict:
    """The replayed night's bundle with its held-out 1-day forecast (S4) as the night's pinned
    forecast, resolved as at pipeline start. The forecast's named candidates take their
    `candidate_id`s on the mayoral rows whose Ballot Names have the same words. Raises unless
    the forecast resolves: a Replay of the variant never runs without it."""
    manifest = HOLDOUT_FORECASTS / f"toronto_{year}.json"
    meta = json.loads(manifest.read_text(encoding="utf-8"))
    ids = {name_words(c["name"]): c["candidate_id"] for c in meta["candidates"]}
    bundle = json.loads(json.dumps(bundle))
    mayor = next(r for r in bundle["races"] if r["office_id"] == MAYOR_OFFICE_ID)
    for row in mayor["candidates"]:
        row["candidate_id"] = ids.get(name_words(row["key"]))
    bundle["forecast"] = {
        "release_tag": f"holdout-1d/{meta['campaign']}",
        "npz": (manifest.parent / meta["npz"]).relative_to(ROOT).as_posix(),
        "npz_sha256": meta["npz_sha256"],
    }
    resolved = resolve_forecast(bundle, ROOT)
    if "forecast_density" not in resolved:
        raise ValueError(f"{year}: the held-out forecast is {resolved['forecast_off']}")
    return resolved


def _forecast_name(candidate_id: str, year: int) -> str:
    """A candidate's name as the night's held-out forecast writes it."""
    path = HOLDOUT_FORECASTS / f"toronto_{year}.json"
    forecast = json.loads(path.read_text(encoding="utf-8"))
    return next(c["name"] for c in forecast["candidates"] if c["candidate_id"] == candidate_id)


# A scored case: (night, race, checkpoint, order), its version, and its scores.
Scored = tuple[tuple, str, CaseScore]


def _scorer(prereg: dict):
    confidence = next(c for c in prereg["pass_criteria"]["criteria"] if c["id"] == 4)
    mass = next(c for c in prereg["pass_criteria"]["criteria"] if c["id"] == 5)
    return lambda case: score_case(case, confidence["confidence"], mass["interval_mass"])


def _key(case: Case) -> tuple:
    return (case.night, case.race, case.checkpoint, case.order)


def _pick(items: list[tuple], variant: str, fallback: str) -> list:
    """From (key, version, item) triples, each key's `variant` item, or its `fallback` item
    where the variant was not in effect."""
    by_key: dict[tuple, dict] = {}
    for key, v, item in items:
        by_key.setdefault(key, {})[v] = item
    return [vs[variant] if variant in vs else vs[fallback] for vs in by_key.values()]


def _pick_cases(cases: list[Case], variant: str, fallback: str) -> list[Case]:
    return _pick([(_key(c), c.variant, c) for c in cases], variant, fallback)


def _switching(scored: list[Scored], variant: str) -> dict:
    """How often the mayor card would switch between the variant and its fallback: along each
    order's scored checkpoints, whether the variant was in effect; a switch between two
    checkpoints counts once, so this is a floor on the refreshes' switches. Retired
    projections and the real captures are left out."""
    by_key: dict[tuple, set[str]] = {}
    retired = set()
    for key, v, score in scored:
        by_key.setdefault(key, set()).add(v)
        if score.retired:
            retired.add(key)
    runs: dict[tuple, list[bool]] = {}
    for key, versions in by_key.items():
        night, race, _, order = key
        if order is not None and key not in retired:
            runs.setdefault((night, race, order), []).append(variant in versions)
    checkpoints = sum(len(r) for r in runs.values())
    fallback = sum(r.count(False) for r in runs.values())
    switches = [sum(a != b for a, b in pairwise(r)) for r in runs.values()]
    return {
        "checkpoints": checkpoints,
        "fallback_checkpoints": fallback,
        "fallback_share": fallback / checkpoints if checkpoints else None,
        "orders": len(runs),
        "switches": sum(switches),
        "orders_with_a_switch": sum(s > 0 for s in switches),
        "mean_switches_per_order": sum(switches) / len(runs) if runs else None,
    }


def _report(nights: dict[int, dict], cases: int) -> dict:
    return {
        "total": totals(nights),
        "nights": {str(y): n for y, n in nights.items()},
        "cases": cases,
    }


def _subsets(by_night: dict[int, dict]) -> dict:
    """The results without 2014 and without 2023, reported only."""
    reported = {}
    for year in (2014, 2023):
        rest = {y: n for y, n in by_night.items() if y != year}
        if year in by_night and rest:
            reported[f"without_{year}"] = _report(rest, sum(n["cases"] for n in rest.values()))
    return reported


def _beats_count_only(variant: dict[int, dict], count_only: dict[int, dict], prereg) -> dict:
    rule = prereg["forecast_weighted_variant"]["beats_count_only"]
    beaten = sum(variant[y]["margin_crps"] < count_only[y]["margin_crps"] for y in variant)
    total = {
        "forecast_weighted": totals(variant)["margin_crps"],
        "count_only": totals(count_only)["margin_crps"],
    }
    return {
        "id": "beats_count_only",
        "name": "beats count-only on total margin CRPS and in enough nights",
        "pass": total["forecast_weighted"] < total["count_only"] and beaten >= rule["min_nights"],
        "value": {"total": total, "nights_beaten": beaten},
        "threshold": {"min_nights": rule["min_nights"], "of_nights": rule["of_nights"]},
    }


def _variant_result(deciding, stress, kept, prereg, bailao) -> dict:
    """The forecast-weighted variant's criteria and reports: count-only first, which fixes the
    fallback, then the variant, its ladder against count-only, and the stress test."""
    variant_rules = prereg["forecast_weighted_variant"]
    if variant_rules["ess_fallback"]["threshold"] != ESS_MIN:
        raise ValueError("the payload's ESS floor is not the pre-registered one")
    count_only = _pick(deciding, "count_only", "count_only")
    co_nights = night_scores(count_only)
    co_checks = criteria(co_nights, prereg, "mayor") + [
        bailao(_pick_cases(kept, "count_only", "count_only"))
    ]
    co_passed = all(c["pass"] for c in co_checks)
    fallback = "count_only" if co_passed else "tally"

    weighted = _pick(deciding, "forecast_weighted", fallback)
    by_night = night_scores(weighted)
    checks = criteria(by_night, prereg, "mayor")
    checks.append(bailao(_pick_cases(kept, "forecast_weighted", fallback)))
    checks.append(_beats_count_only(by_night, co_nights, prereg))

    stress_test = _pick(deciding, "stress_test", fallback)
    st_nights = night_scores(stress_test)
    st_checks = criteria(st_nights, prereg, "mayor")
    st_checks.append(bailao(_pick_cases(kept, "stress_test", fallback)))
    must = variant_rules["wrong_forecast_stress_test"]["must_meet"]
    if must != [4, 6]:
        raise ValueError(f"the stress test must meet {must}, not G1 and criterion 6")
    for check, name in zip((st_checks[3], st_checks[5]), ("stress_g1", "stress_bailao")):
        checks.append({**check, "id": name, "name": f"wrong-forecast stress test: {check['name']}"})

    reported = _subsets(by_night)
    reported["count_only"] = {
        "pass": co_passed,
        "criteria": co_checks,
        "cases": len(count_only),
        "scores": _report(co_nights, len(count_only)),
    }
    reported["stress_test"] = {
        "shift_points": prereg["stress_test_shift"]["shift_points"],
        "criteria": st_checks,
        "scores": _report(st_nights, len(stress_test)),
    }
    reported["fallback"] = fallback
    reported["switching"] = {
        "forecast_weighted": _switching(deciding, "forecast_weighted"),
        "stress_test": _switching(deciding, "stress_test"),
    }
    if stress:
        orders = _pick(stress, "forecast_weighted", fallback)
        reported["stress_orders"] = _report(night_scores(orders), len(orders))
        reported["stress_orders"]["switching"] = _switching(stress, "forecast_weighted")
    return {"checks": checks, "by_night": by_night, "cases": len(weighted), "reported": reported}


def _order_scores(state: dict, task: tuple[int, str, int, np.ndarray]) -> list[Scored]:
    """Replay one arrival order and score its cases: the unit of work, serial or pooled."""
    year, kind, index, order = task
    score = _scorer(state["prereg"])
    cases = order_cases(
        state["nights"][year],
        order,
        f"{kind}-{index}",
        LEVELS[state["level_name"]],
        state["prereg"],
        state["model_version"],
        state["project"],
        state["make_bundle"],
    )
    return [(_key(case), case.variant, score(case)) for case in cases]


# A pool worker's replay state, set once per worker process (`_start_worker`).
_WORKER_STATE: dict = {}


def _start_worker(state: dict) -> None:
    _WORKER_STATE.update(state)


def _pooled_order_scores(task: tuple[int, str, int, np.ndarray]) -> list[Scored]:
    return _order_scores(_WORKER_STATE, task)


def _bundle_from(bundles: dict[int, dict], night: Night) -> dict:
    return bundles[night.year]


def replay_level(
    level_name: str,
    prereg: dict,
    nights: dict[int, Night],
    orders: dict[int, list[tuple[str, int, np.ndarray]]],
    captures: list[Capture],
    model_version: str,
    smoke: bool = False,
    project=payload.project,
    make_bundle=night_bundle,
    workers: int = 1,
    on_order=None,
) -> dict:
    """The level's Gate Result, without its run number. With `workers` above 1 the orders fan
    out over a process pool (`project` and `make_bundle` must then pickle); their scores come
    back in the orders' own sequence, so the result is the serial one. `on_order(done, total)`
    is called as each order's scores arrive."""
    level = LEVELS[level_name]
    patterns = set(prereg["arrival_orders"]["ward_aggregates"]["timing_patterns"])
    score = _scorer(prereg)
    deciding: list[Scored] = []
    stress: list[Scored] = []
    kept: list[Case] = []  # the real captures' cases, for the Bailão check

    def take(cases: list[Case], into: list[Scored]) -> None:
        for case in cases:
            into.append((_key(case), case.variant, score(case)))
            if case.order is None:
                kept.append(case)

    tasks = [(year, kind, index, order) for year in nights for kind, index, order in orders[year]]
    state = {
        "level_name": level_name,
        "prereg": prereg,
        "nights": nights,
        "model_version": model_version,
        "project": project,
        "make_bundle": make_bundle,
    }
    if workers > 1:
        pool = ProcessPoolExecutor(workers, initializer=_start_worker, initargs=(state,))
        results = pool.map(_pooled_order_scores, tasks)
    else:
        pool = None
        results = map(partial(_order_scores, state), tasks)
    try:
        for done, ((_, kind, _, _), scored) in enumerate(zip(tasks, results), start=1):
            (deciding if kind in patterns else stress).extend(scored)
            if on_order is not None:
                on_order(done, len(tasks))
    except BaseException:
        # A timeout or a worker's error ends the run now, not after the orders in flight.
        if pool is not None:
            pool.terminate_workers()
        raise
    if pool is not None:
        pool.shutdown()
    for capture in captures:
        if capture.night in nights:
            night = nights[capture.night]
            cases = capture_cases(
                night, capture, level, prereg, model_version, project, make_bundle
            )
            take(cases, deciding)

    six = next(c for c in prereg["pass_criteria"]["criteria"] if c["id"] == 6)
    name = (
        _forecast_name(six["candidate_id"], BAILAO_NIGHT) if level.name in six["levels"] else None
    )

    def bailao(cases: list[Case]) -> dict:
        return bailao_check(cases, prereg, name)

    if level.variant == "forecast_weighted":
        found = _variant_result(deciding, stress, kept, prereg, bailao)
        checks, by_night, cases = found["checks"], found["by_night"], found["cases"]
        reported = found["reported"]
    else:
        scores = [s for _, _, s in deciding]
        by_night = night_scores(scores)
        checks = criteria(by_night, prereg, level.name)
        if name is not None:
            checks.append(bailao(kept))
        cases = len(scores)
        reported = _subsets(by_night)
        if stress:
            reported["stress_orders"] = _report(
                night_scores([s for _, _, s in stress]), len(stress)
            )
    kinds = [kind for year in orders for kind, _, _ in orders[year]]
    per_night = max(1, len(nights))
    return {
        "level": level_name,
        "variant": level.variant,
        "smoke": smoke,
        "pass": all(c["pass"] for c in checks),
        "criteria": checks,
        "scores": _report(by_night, cases),
        "nights": sorted(nights),
        "cases": cases,
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


def run_replay(
    level_name: str,
    prereg: dict,
    years: list[int],
    smoke: bool,
    workers: int = 1,
    on_order=None,
) -> tuple[dict, dict]:
    """Load the nights, draw the orders and replay the level. A smoke run takes the first order
    of each timing pattern and of each stress kind, so its report-only results are filled.
    Returns the Gate Result and timing figures."""
    import time

    from election_night.projection.history import replay_bundle
    from election_night.replay.captures import real_captures
    from election_night.replay.gate_result import model_files, model_version
    from election_night.replay.historical import YEARS, load_night
    from election_night.replay.orders import arrival_order, orders

    start = time.monotonic()
    # Every night is loaded for the folds' history; only `years` are replayed.
    history = {year: load_night(year, prereg) for year in YEARS}
    nights = {year: history[year] for year in years}
    bundles = {year: replay_bundle(history[year], history, prereg) for year in years}
    if LEVELS[level_name].variant == "forecast_weighted":
        bundles = {year: with_holdout_forecast(b, year) for year, b in bundles.items()}
    patterns = list(prereg["arrival_orders"]["ward_aggregates"]["timing_patterns"])
    if smoke:
        kinds = patterns + list(prereg["arrival_orders"]["stress_orders"]["kinds"])
        drawn = {
            y: [(kind, 0, arrival_order(n, prereg, kind, 0)) for kind in kinds]
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
    result = replay_level(
        level_name,
        prereg,
        nights,
        drawn,
        captures,
        version,
        smoke=smoke,
        make_bundle=partial(_bundle_from, bundles),
        workers=workers,
        on_order=on_order,
    )
    done = time.monotonic()
    if LEVELS[level_name].variant == "forecast_weighted":
        # The forecast is an input, outside the model version (gate_result.forecast_in_hash).
        result["forecast_inputs"] = {
            str(year): {
                "release_tag": b["forecast"]["release_tag"],
                "npz_sha256": b["forecast"]["npz_sha256"],
            }
            for year, b in bundles.items()
        }
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
