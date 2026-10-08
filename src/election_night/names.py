"""Ballot Names for the Night Bundle: candidacy ids, short labels and forecast ids (#16).

Three sources name the 2026 candidates: the City's test file, the City registry and the canonical
results. All three copy the registry today, so the bundle build asserts they match one to one in
every race and fails otherwise: a mismatch must stop the build, not the night. The inputs are
vendored and loaded by `election_night.name_inputs`.
"""

import json
from collections import Counter
from dataclasses import dataclass
from typing import NamedTuple

from election_night.feed import COUNCILLOR_OFFICE_ID, MAYOR_OFFICE_ID, race_id

# The canonical's `represented_body` for each school board's feed office id. Mayor and councillor
# share `toronto_city_council` and are told apart by `office_type`.
CITY_COUNCIL = "toronto_city_council"
SCHOOL_BOARDS = {
    "toronto_district_school_board": 3,
    "toronto_catholic_district_school_board": 4,
    "conseil_scolaire_viamonde": 5,
    "conseil_scolaire_catholique_monavenir": 6,
}


class NameMismatch(ValueError):
    """The test file, registry and canonical don't name the same candidates in every race."""


class ForecastUnmatched(ValueError):
    """A forecast-named mayoral candidate doesn't sit on exactly one mayoral row."""


class Candidacy(NamedTuple):
    candidacy_id: str
    person_id: str | None


@dataclass(frozen=True)
class NameInputs:
    registry: dict[str, dict[str, str]]  # race id -> Ballot Name -> registry lastName
    canonical: dict[str, dict[str, Candidacy]]  # race id -> Ballot Name -> its candidacy
    forecast_ids: list[str]  # the forecast's named mayoral candidate_ids
    source: dict  # provenance, recorded in the bundle


def _add_once(races: dict, race: str, name: str, value) -> None:
    names = races.setdefault(race, {})
    if name in names:
        raise NameMismatch(f"{race}: {name!r} appears twice")
    names[name] = value


def registry_races(mayor: bytes, councillor: bytes, trustee: bytes) -> dict[str, dict[str, str]]:
    """Each race's Active registry candidates: Ballot Name -> `lastName`."""
    races: dict[str, dict[str, str]] = {}

    def add_race(office_id: int, num: str, candidates: list[dict]) -> None:
        for c in candidates:
            if c["status"] != "Active":
                continue
            first, last = (c.get("firstName") or "").strip(), (c.get("lastName") or "").strip()
            name = f"{first} {last}" if first else last
            _add_once(races, race_id(office_id, num), name, last)

    add_race(MAYOR_OFFICE_ID, "0", json.loads(mayor)["candidates"])
    for ward in json.loads(councillor)["ward"]:
        add_race(COUNCILLOR_OFFICE_ID, ward["num"], ward["candidate"])
    for board in json.loads(trustee)["schoolBoard"]:
        wards = board["ward"] if isinstance(board["ward"], list) else [board["ward"]]
        for ward in wards:
            add_race(board["id"], ward["num"], ward["candidate"])
    return races


def canonical_races(rows: list[dict[str, str]]) -> dict[str, dict[str, Candidacy]]:
    """Each race's 2026 candidacies, by Ballot Name, from canonical `election_results` rows."""
    races: dict[str, dict[str, Candidacy]] = {}
    for row in rows:
        body = row["represented_body"]
        if body == CITY_COUNCIL:
            office_id = MAYOR_OFFICE_ID if row["office_type"] == "mayor" else COUNCILLOR_OFFICE_ID
        elif body in SCHOOL_BOARDS:
            office_id = SCHOOL_BOARDS[body]
        else:
            continue
        num = "0" if office_id == MAYOR_OFFICE_ID else row["official_district_id"]
        candidacy = Candidacy(row["candidacy_id"], row["person_id"] or None)
        _add_once(
            races, race_id(office_id, num.removeprefix("ward-")), row["candidate_name"], candidacy
        )
    return races


def short_labels(last_names: dict[str, str]) -> dict[str, str]:
    """The registry `lastName`, or the full Ballot Name when there is none or it repeats."""
    repeats = Counter(last_names.values())
    return {
        name: last if last and repeats[last] == 1 else name for name, last in last_names.items()
    }


def _mismatches(races: list[dict], label: str, source: dict[str, dict]) -> list[str]:
    problems = [
        f"{extra}: in the {label}, not the test file"
        for extra in sorted(set(source) - {race["id"] for race in races})
    ]
    for race in races:
        feed = {c["key"] for c in race["candidates"]}
        theirs = set(source.get(race["id"], {}))
        if missing := sorted(feed - theirs):
            problems.append(f"{race['id']}: not in the {label}: {missing}")
        if extra := sorted(theirs - feed):
            problems.append(f"{race['id']}: in the {label}, not the test file: {extra}")
    return problems


def name_races(races: list[dict], names: NameInputs) -> list[dict]:
    """The bundle's races with each candidate's `candidacy_id`, short label and forecast id.

    Fails unless the test file, registry and canonical name the same candidates in every race,
    and unless each forecast-named mayoral candidate sits on exactly one mayoral row, matched by
    `person_id` or `candidacy_id`.
    """
    problems = _mismatches(races, "registry", names.registry)
    problems += _mismatches(races, "canonical", names.canonical)
    if problems:
        raise NameMismatch("; ".join(problems))

    candidate_ids = {}
    for forecast_id in names.forecast_ids:
        rows = [name for name, ids in names.canonical["mayor"].items() if forecast_id in ids]
        if len(rows) != 1:
            raise ForecastUnmatched(f"{forecast_id} matches {len(rows)} mayoral rows: {rows}")
        candidate_ids[rows[0]] = forecast_id

    named = []
    for race in races:
        labels = short_labels(names.registry[race["id"]])
        canonical = names.canonical[race["id"]]
        is_mayor = race["office_id"] == MAYOR_OFFICE_ID
        candidates = [
            {
                "key": c["key"],
                "short_label": labels[c["key"]],
                "candidacy_id": canonical[c["key"]].candidacy_id,
                "candidate_id": candidate_ids.get(c["key"]) if is_mayor else None,
            }
            for c in race["candidates"]
        ]
        named.append({**race, "candidates": candidates})
    return named
