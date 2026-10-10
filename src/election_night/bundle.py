"""The Night Bundle: the fixed inputs election night runs on.

The bundle is built from a pair of the City's test files: the races, each race's `polls`, the
opening time and the Ballot Names as written, in ballot order. For 2026 the build also names every
candidate from the registry and the canonical (`election_night.names`) and fails unless all three
match one to one. Historical bundles for Replays and goldens have no registry and keep those
fields null.

The 2026 Night Bundle (`build_night_bundle`, #46) adds each projected race's expected totals and
Ward Aggregate sizes, the frozen parameters fitted on every historical night, every Gate Result
and the pinned final forecast's draws with their release tag.
"""

import hashlib
import json
import math
import os
from datetime import datetime
from pathlib import Path

from election_night.feed import (
    MAYOR_OFFICE_ID,
    OFFICES,
    UnreadableRow,
    count,
    race_id,
    read_all_office,
    read_ward_by_ward,
)
from election_night.names import NameInputs, name_races
from election_night.projection.history import (
    Released,
    fit_params,
    race_inputs,
    structure_2026,
)

BUNDLE_VERSION = 1
STUB_MODEL_VERSION = "stub-v0"
OPENING_2026 = "2026-10-26T20:00:00-04:00"  # 20:00 EDT on election night
PARAMS = "params/night.json"  # under gates/: the night's frozen parameters, in the model version


def _candidates(names: list[str]) -> list[dict]:
    return [
        {"key": name, "short_label": None, "candidacy_id": None, "candidate_id": None}
        for name in names
    ]


def _electors(w) -> dict[str, int] | None:
    """Each City ward's electors (`totalVoters`) in the ward-by-ward test file, or None if any
    is unreadable. The Possible Range's bound on the outstanding votes (ADR 0002)."""
    candidates = w.office["candidate"]
    if not candidates:
        return None
    try:
        return {ward["num"]: count(ward.get("totalVoters")) for ward in candidates[0]["ward"]}
    except UnreadableRow, KeyError, TypeError:
        return None


def build_bundle(
    all_office: bytes,
    ward_by_ward: bytes,
    opening_time: str,
    names: NameInputs | None = None,
    trustee_wards: dict[tuple[int, str], tuple[int, ...]] | None = None,
    forecast_only: bool = False,
) -> dict:
    """Build the Night Bundle from a pair of the City's test files.

    `opening_time` is an ISO 8601 time with its UTC offset, the time before which every payload is
    in the "before results" state. The test files must be fully readable. With `names`, every
    candidate gains its `candidacy_id`, short label and any forecast `candidate_id`, and the build
    raises `NameMismatch` or `ForecastUnmatched` unless the sources agree; `forecast_only` leaves
    an unmatched forecast id off rather than raise. With `trustee_wards`,
    each trustee area records the City wards it covers (`city_wards`), keyed by (office id,
    area num).
    """
    datetime.fromisoformat(opening_time)  # must parse, offset included
    a = read_all_office(all_office)
    w = read_ward_by_ward(ward_by_ward)

    mayor_tally = w.tally()
    races = [
        {
            "id": race_id(MAYOR_OFFICE_ID, "0"),
            "office_id": MAYOR_OFFICE_ID,
            "level": OFFICES[MAYOR_OFFICE_ID][1],
            "num": "0",
            "name": "City-wide",
            "polls": mayor_tally.polls,
            "acclaimed": len(mayor_tally.votes) == 1,
            "candidates": _candidates(list(mayor_tally.votes)),
            "wards": [
                {"num": ward.num, "name": ward.name, "polls": ward.polls} for ward in w.wards()
            ],
        }
    ]
    for (office_id, num), row in sorted(a.rows.items(), key=lambda kv: (kv[0][0], int(kv[0][1]))):
        if office_id == MAYOR_OFFICE_ID or office_id not in OFFICES:
            continue
        tally = a.tally(office_id, num)
        name = row.get("name")
        races.append(
            {
                "id": race_id(office_id, num),
                "office_id": office_id,
                "level": OFFICES[office_id][1],
                "num": num,
                "name": name if isinstance(name, str) else None,
                "polls": count(row.get("polls")),
                "acclaimed": len(tally.votes) == 1,
                "candidates": _candidates(list(tally.votes)),
            }
        )
        covered = (trustee_wards or {}).get((office_id, num))
        if covered:
            races[-1]["city_wards"] = [str(ward) for ward in covered]
    source = {
        "all_office": {"seq": a.seq, "sha256": hashlib.sha256(all_office).hexdigest()},
        "ward_by_ward": {"seq": w.seq, "sha256": hashlib.sha256(ward_by_ward).hexdigest()},
    }
    if names is not None:
        races = name_races(races, names, forecast_only)
        source["names"] = names.source
    return {
        "bundle_version": BUNDLE_VERSION,
        "model_version": STUB_MODEL_VERSION,
        "forecast_release_tag": None,
        "opening_time": opening_time,
        "electors": _electors(w),
        "source": source,
        "races": races,
    }


def write_bundle(bundle: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def load_bundle(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_advance(path: Path) -> tuple[Released, dict]:
    """The City's 2026 advance figure as recorded (S5), its ladder path, and the record with its
    sha256. A ward table wins, else the citywide figure; with neither, the ladder's fallback,
    historical shares. A figure must name its source and date."""
    body = path.read_bytes()
    record = json.loads(body)
    wards = record.get("wards") or {}
    voters = record.get("advance_voters")
    if (wards or voters is not None) and not (
        record.get("source_url") and record.get("published_date")
    ):
        raise ValueError(f"{path.name}: a released figure needs its source_url and published_date")
    if wards:
        path_taken = "ward_table"
    elif voters is not None:
        path_taken = "citywide"
    else:
        path_taken = "historical_shares"
    released = (path_taken, voters, {int(w): int(v) for w, v in wards.items()})
    return released, {**record, "sha256": hashlib.sha256(body).hexdigest()}


def _forecast(names: NameInputs, bundle_dir: Path) -> dict | None:
    """The pointer to the pinned forecast's draws, relative to the bundle, as vendored."""
    draws = names.source.get("forecast", {}).get("draws")
    if draws is None or names.directory is None:
        return None
    return {
        "release_tag": names.source["forecast"]["release"],
        "npz": Path(os.path.relpath(names.directory / draws["asset"], bundle_dir)).as_posix(),
        "npz_sha256": draws["sha256"],
    }


def build_night_bundle(
    city: Path,
    names: NameInputs,
    opening_time: str,
    trustee_wards_csv: Path,
    gates: Path,
    advance: Path,
    *,
    bundle_dir: Path,
    forecast_only: bool = False,
) -> dict:
    """The 2026 Night Bundle from its committed inputs: the City's test files in `city`, the
    name inputs, the trustee areas' City wards, every Gate Result and approval under `gates`
    (#45), the frozen parameters in `gates/params/night.json` and the City's 2026 advance figure
    in `advance` (#46). Fails unless the frozen parameters equal a fresh fit on every historical
    night. The forecast's draws are pointed to relative to `bundle_dir`, where the bundle is
    written. `forecast_only` is the forecast-only rebuild: an unmatched forecast turns the
    mayor's variant off instead of failing the build (#16)."""
    from election_night.mockfeed.scenario import read_trustee_wards
    from election_night.replay.gate_result import gate_records, model_files, model_version

    bundle = build_bundle(
        (city / "unofficialresult.json").read_bytes(),
        (city / "unofficialresult-wardbyward.json").read_bytes(),
        opening_time,
        names=names,
        trustee_wards=read_trustee_wards(trustee_wards_csv.read_text(encoding="utf-8")),
        forecast_only=forecast_only,
    )
    bundle["gates"] = gate_records(gates / "results", gates / "approvals")
    bundle["model_version"] = model_version(gates.parent, model_files(gates.parent))

    nights = _history(gates)
    frozen = json.loads((gates / PARAMS).read_text(encoding="utf-8"))
    if not _same_params(fit_params(nights), frozen):
        raise ValueError(f"{PARAMS} differs from a fresh fit: run `uv run election-night params`")
    released, record = read_advance(advance)
    electors = {int(ward): n for ward, n in bundle["electors"].items()}
    inputs = race_inputs(structure_2026(bundle["races"]), nights, electors, released)
    for spec in bundle["races"]:
        if spec["id"] in inputs:
            spec["expected"] = inputs[spec["id"]]
    bundle["projection"] = {"params": frozen}
    bundle["ward_aggregates"] = {
        "path": released[0],
        "advance_voters": released[1],
        "source": record,
    }
    if forecast := _forecast(names, bundle_dir):
        bundle["forecast"] = forecast
        bundle["forecast_release_tag"] = forecast["release_tag"]
    return bundle


def _same_params(fitted: dict, frozen: dict) -> bool:
    """Whether a fresh fit equals the frozen parameters, to within float error across CPUs."""
    return fitted.keys() == frozen.keys() and all(
        fitted[level].keys() == frozen[level].keys()
        and all(math.isclose(fitted[level][k], v, rel_tol=1e-9) for k, v in frozen[level].items())
        for level in frozen
    )


def _history(gates: Path) -> list:
    """Every historical night, with Ward Aggregates as pre-registered."""
    from election_night.gates import load_preregistration
    from election_night.replay.historical import YEARS, load_night

    prereg = load_preregistration(gates / "preregistration.json")
    return [load_night(year, prereg) for year in YEARS]


def night_params(gates: Path) -> dict:
    """Each level's parameters fitted on every historical night, as `gates/params/night.json`
    freezes them."""
    return fit_params(_history(gates))
