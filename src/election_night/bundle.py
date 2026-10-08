"""The Night Bundle: the fixed inputs election night runs on.

Bundle v0 is built from a pair of the City's test files: the races, each race's `polls`, the opening
time and the Ballot Names as written, in ballot order. Later tickets add the rest; the fields they
fill are present and null.
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path

from election_night.feed import (
    MAYOR_OFFICE_ID,
    OFFICES,
    count,
    read_all_office,
    read_ward_by_ward,
)

BUNDLE_VERSION = 0
STUB_MODEL_VERSION = "stub-v0"
OPENING_2026 = "2026-10-26T20:00:00-04:00"  # 20:00 EDT on election night


def race_id(office_id: int, num: str) -> str:
    prefix = OFFICES[office_id][0]
    return prefix if office_id == MAYOR_OFFICE_ID else f"{prefix}-{num}"


def _candidates(names: list[str]) -> list[dict]:
    return [
        {"key": name, "short_label": None, "candidacy_id": None, "candidate_id": None}
        for name in names
    ]


def build_bundle(
    all_office: bytes,
    ward_by_ward: bytes,
    opening_time: str,
) -> dict:
    """Build Night Bundle v0 from a pair of the City's test files.

    `opening_time` is an ISO 8601 time with its UTC offset, the time before which every payload is
    in the "before results" state. The test files must be fully readable.
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
    return {
        "bundle_version": BUNDLE_VERSION,
        "model_version": STUB_MODEL_VERSION,
        "forecast_release_tag": None,
        "opening_time": opening_time,
        "source": {
            "all_office": {"seq": a.seq, "sha256": hashlib.sha256(all_office).hexdigest()},
            "ward_by_ward": {"seq": w.seq, "sha256": hashlib.sha256(ward_by_ward).hexdigest()},
        },
        "races": races,
    }


def write_bundle(bundle: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def load_bundle(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
