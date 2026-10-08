"""The real captures as named checkpoints (`gates/preregistration.json` § real_captures).

Each capture is one of the City's files as the Wayback Machine kept it on the night. It becomes a
Count Snapshot pair in its Replay's terms: its partner file is the night's zeroed counterpart at
the capture's `seq`, and its Ballot Names (`Olivia Chow`) are rewritten to the workbook's
(`Chow Olivia`), so it is scored against the same certified totals as the simulated checkpoints.
Names are matched by their words, ignoring order and case, and every workbook candidate must match
exactly one feed name. A feed name with no workbook match is kept as written only if it has no
votes: 2022 Ward 23 lists Cynthia Lai, who died during the campaign, at 0, and the certified
workbook leaves her out.
"""

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from election_night.replay.historical import Night, Race
from election_night.replay.snapshots import zeroed_pair


@dataclass(frozen=True)
class Capture:
    night: int
    time_edt: str
    file: str  # "all-office" or "ward-by-ward": which file is the real one
    all_office: bytes
    ward_by_ward: bytes


def _words(name: str) -> tuple[str, ...]:
    return tuple(sorted(unicodedata.normalize("NFC", name).casefold().split()))


def _rename(race: Race, candidates: list[dict], where: str) -> None:
    ours = {_words(c): c for c in race.candidates}
    if len(ours) != len(race.candidates):
        raise ValueError(f"{where}: two workbook names share their words")
    mapped = [ours.get(_words(c["name"])) for c in candidates]
    unmatched = [c for c, m in zip(candidates, mapped) if m is None]
    if any(c["votesReceived"] != "0" for c in unmatched) or sorted(
        m for m in mapped if m is not None
    ) != sorted(race.candidates):
        raise ValueError(f"{where}: names don't match the workbook one to one")
    for candidate, name in zip(candidates, mapped):
        if name is not None:
            candidate["name"] = name


def _restamped(body: bytes, seq: str) -> bytes:
    data = json.loads(body)
    data["seq"] = seq
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


def _capture(entry: dict, root: Path, night: Night) -> Capture:
    body = (root / entry["path"]).read_bytes()
    if hashlib.sha256(body).hexdigest() != entry["sha256"]:
        raise ValueError(f"{entry['path']}: sha256 differs from the pre-registration file")
    data = json.loads(body)
    races = {(r.office_id, r.num): r for r in night.races}
    zero = zeroed_pair(night)
    if entry["file"] == "all-office":
        for office in data["office"]:
            for row in office["ward"]:
                race = races.get((office["id"], row["num"]))
                if race is not None:
                    _rename(race, row["candidate"], f"{entry['path']} {office['id']}/{row['num']}")
        all_office = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        ward_by_ward = _restamped(zero.ward_by_ward, data["seq"])
    elif entry["file"] == "ward-by-ward":
        _rename(night.races[0], data["office"]["candidate"], entry["path"])
        ward_by_ward = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        all_office = _restamped(zero.all_office, data["seq"])
    else:
        raise ValueError(f"unknown capture file {entry['file']!r}")
    return Capture(entry["night"], entry["time_edt"], entry["file"], all_office, ward_by_ward)


def real_captures(prereg: dict, root: Path, nights: dict[int, Night]) -> list[Capture]:
    """Every pre-registered capture, council and trustee first, in the file's order."""
    listed = prereg["real_captures"]
    entries = listed["council_and_trustee"] + listed["mayor"]
    return [_capture(e, root, nights[e["night"]]) for e in entries]
