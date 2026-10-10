"""The Night Bundle: the fixed inputs election night runs on.

The bundle is built from a pair of the City's test files: the races, each race's `polls`, the
opening time and the Ballot Names as written, in ballot order. For 2026 the build also names every
candidate from the registry and the canonical (`election_night.names`) and fails unless all three
match one to one. Historical bundles for Replays and goldens have no registry and keep those
fields null. Later tickets add the rest; the fields they fill are present and null.
"""

import hashlib
import json
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

BUNDLE_VERSION = 1
STUB_MODEL_VERSION = "stub-v0"
OPENING_2026 = "2026-10-26T20:00:00-04:00"  # 20:00 EDT on election night


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
) -> dict:
    """Build the Night Bundle from a pair of the City's test files.

    `opening_time` is an ISO 8601 time with its UTC offset, the time before which every payload is
    in the "before results" state. The test files must be fully readable. With `names`, every
    candidate gains its `candidacy_id`, short label and any forecast `candidate_id`, and the build
    raises `NameMismatch` or `ForecastUnmatched` unless the sources agree. With `trustee_wards`,
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
        races = name_races(races, names)
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


def build_night_bundle(
    city: Path, names: NameInputs, opening_time: str, trustee_wards_csv: Path, gates: Path
) -> dict:
    """The 2026 Night Bundle from its committed inputs: the City's test files in `city`, the
    name inputs, the trustee areas' City wards, and every Gate Result and approval under `gates`
    (#45)."""
    from election_night.mockfeed.scenario import read_trustee_wards
    from election_night.replay.gate_result import gate_records

    bundle = build_bundle(
        (city / "unofficialresult.json").read_bytes(),
        (city / "unofficialresult-wardbyward.json").read_bytes(),
        opening_time,
        names=names,
        trustee_wards=read_trustee_wards(trustee_wards_csv.read_text(encoding="utf-8")),
    )
    bundle["gates"] = gate_records(gates / "results", gates / "approvals")
    return bundle
