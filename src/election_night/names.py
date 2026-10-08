"""Ballot Names for the Night Bundle: candidacy ids, short labels and forecast ids (#16).

Three sources name the 2026 candidates: the City's test file, the City registry and the canonical
results. All three copy the registry today, so the bundle build asserts they match one to one in
every race and fails otherwise: a mismatch must stop the build, not the night.

The inputs are vendored in `data/night-bundle/inputs/` by `fetch_name_inputs`, from the registry
URLs and from the Results release the pinned forecast was built from. The registry copies keep
only the name fields; `sources.json` records each original's `seq` and sha256.
"""

import csv
import hashlib
import io
import json
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from election_night.feed import MAYOR_OFFICE_ID, race_id

REGISTRY_URL = "https://www.toronto.ca/data/elections/candidate_list/{}"
REGISTRY_FILES = (
    "mayorCandidates_2026.json",
    "councilorCandidates_2026.json",
    "trusteeCandidates_2026.json",
)
RELEASE_URL = "https://github.com/{repo}/releases/download/{tag}/{asset}"
BACKEND_REPO = "alexwolson/toronto-election-poll-tracker-backend"
FORECAST_RECORD = "mayoral_forecast_draws.json"
CANONICAL_ASSET = "election_results.csv"
ELECTION_DATE = "2026-10-26"

# The canonical's `represented_body` for each feed office id.
CANONICAL_BODIES = {
    "toronto_city_council": None,  # mayor and councillor, told apart by `office_type`
    "toronto_district_school_board": 3,
    "toronto_catholic_district_school_board": 4,
    "conseil_scolaire_viamonde": 5,
    "conseil_scolaire_catholique_monavenir": 6,
}
CANONICAL_COLUMNS = (
    "candidacy_id",
    "person_id",
    "office_type",
    "represented_body",
    "official_district_id",
    "candidate_name",
)
REGISTRY_FIELDS = ("name", "office", "status", "firstName", "lastName")


class NameMismatch(ValueError):
    """The test file, registry and canonical don't name the same candidates in every race."""


class ForecastUnmatched(ValueError):
    """A forecast-named mayoral candidate doesn't sit on exactly one mayoral row."""


@dataclass(frozen=True)
class NameInputs:
    registry: dict[str, dict[str, str]]  # race id -> Ballot Name -> registry lastName
    canonical: dict[str, dict[str, tuple[str, str | None]]]  # -> (candidacy_id, person_id)
    forecast_ids: list[str]  # the forecast's named mayoral candidate_ids
    source: dict  # provenance, recorded in the bundle


def _add(races: dict, race: str, name: str, value) -> None:
    names = races.setdefault(race, {})
    if name in names:
        raise NameMismatch(f"{race}: {name!r} appears twice")
    names[name] = value


def registry_races(mayor: bytes, councillor: bytes, trustee: bytes) -> dict[str, dict[str, str]]:
    """Each race's Active registry candidates: Ballot Name -> `lastName`."""
    races: dict[str, dict[str, str]] = {}

    def add(office_id: int, num: str, candidates: list[dict]) -> None:
        for c in candidates:
            if c["status"] != "Active":
                continue
            first, last = (c.get("firstName") or "").strip(), (c.get("lastName") or "").strip()
            name = f"{first} {last}" if first else last
            _add(races, race_id(office_id, num), name, last)

    add(MAYOR_OFFICE_ID, "0", json.loads(mayor)["candidates"])
    for ward in json.loads(councillor)["ward"]:
        add(2, ward["num"], ward["candidate"])
    for board in json.loads(trustee)["schoolBoard"]:
        wards = board["ward"] if isinstance(board["ward"], list) else [board["ward"]]
        for ward in wards:
            add(board["id"], ward["num"], ward["candidate"])
    return races


def canonical_races(rows) -> dict[str, dict[str, tuple[str, str | None]]]:
    """Each race's 2026 candidacies: Ballot Name -> (`candidacy_id`, `person_id`)."""
    races: dict[str, dict[str, tuple[str, str | None]]] = {}
    for row in rows:
        body = row["represented_body"]
        if body not in CANONICAL_BODIES:
            continue
        if body == "toronto_city_council":
            office_id = MAYOR_OFFICE_ID if row["office_type"] == "mayor" else 2
        else:
            office_id = CANONICAL_BODIES[body]
        num = "0" if office_id == MAYOR_OFFICE_ID else row["official_district_id"]
        num = num.removeprefix("ward-")
        value = (row["candidacy_id"], row["person_id"] or None)
        _add(races, race_id(office_id, num), row["candidate_name"], value)
    return races


def short_labels(last_names: dict[str, str]) -> dict[str, str]:
    """The registry `lastName`, or the full Ballot Name when there is none or it repeats."""
    repeats = Counter(last_names.values())
    return {
        name: last if last and repeats[last] == 1 else name for name, last in last_names.items()
    }


def name_races(races: list[dict], names: NameInputs) -> list[dict]:
    """The bundle's races with each candidate's `candidacy_id`, short label and forecast id.

    Fails unless the test file, registry and canonical name the same candidates in every race,
    and unless each forecast-named mayoral candidate sits on exactly one mayoral row.
    """
    problems = []
    race_ids = {race["id"] for race in races}
    for label, source in (("registry", names.registry), ("canonical", names.canonical)):
        for extra in sorted(set(source) - race_ids):
            problems.append(f"{extra}: in the {label}, not the test file")
    for race in races:
        feed = [c["key"] for c in race["candidates"]]
        for label, source in (("registry", names.registry), ("canonical", names.canonical)):
            theirs = source.get(race["id"], {})
            if missing := sorted(set(feed) - set(theirs)):
                problems.append(f"{race['id']}: not in the {label}: {missing}")
            if extra := sorted(set(theirs) - set(feed)):
                problems.append(f"{race['id']}: in the {label}, not the test file: {extra}")
    if problems:
        raise NameMismatch("; ".join(problems))

    mayor = next(race for race in races if race["office_id"] == MAYOR_OFFICE_ID)
    candidate_ids = {}
    for forecast_id in names.forecast_ids:
        rows = [
            name
            for name, ids in names.canonical["mayor"].items()
            if forecast_id in ids and name in {c["key"] for c in mayor["candidates"]}
        ]
        if len(rows) != 1:
            raise ForecastUnmatched(f"{forecast_id} matches {len(rows)} mayoral rows: {rows}")
        candidate_ids[rows[0]] = forecast_id

    named = []
    for race in races:
        labels = short_labels(names.registry[race["id"]])
        canonical = names.canonical[race["id"]]
        candidates = [
            {
                "key": c["key"],
                "short_label": labels[c["key"]],
                "candidacy_id": canonical[c["key"]][0],
                "candidate_id": candidate_ids.get(c["key"]) if race is mayor else None,
            }
            for c in race["candidates"]
        ]
        named.append({**race, "candidates": candidates})
    return named


def load_name_inputs(directory: Path) -> NameInputs:
    """The vendored name inputs, as `fetch_name_inputs` wrote them."""
    registry = registry_races(*((directory / "registry" / f).read_bytes() for f in REGISTRY_FILES))
    with (directory / "canonical-2026.csv").open(encoding="utf-8", newline="") as f:
        canonical = canonical_races(csv.DictReader(f))
    record = json.loads((directory / FORECAST_RECORD).read_text(encoding="utf-8"))
    source = json.loads((directory / "sources.json").read_text(encoding="utf-8"))
    return NameInputs(
        registry, canonical, [c["candidate_id"] for c in record["candidates"]], source
    )


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def _trimmed_registry(body: bytes) -> bytes:
    """The registry file with only its structure, `seq` and each candidate's name fields."""

    def trim(value):
        if isinstance(value, list):
            return [trim(v) for v in value]
        if not isinstance(value, dict):
            return value
        if "firstName" in value or "lastName" in value:
            return {k: value[k] for k in REGISTRY_FIELDS if k in value}
        return {k: trim(v) for k, v in value.items() if k != "spaces"}

    return (json.dumps(trim(json.loads(body)), ensure_ascii=False, indent=1) + "\n").encode()


def fetch_name_inputs(backend_release: str, out: Path) -> dict:
    """Vendor the registry, the forecast's ids and its Results release's 2026 candidacies."""
    sha = lambda body: hashlib.sha256(body).hexdigest()
    fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
    (out / "registry").mkdir(parents=True, exist_ok=True)

    registry = {}
    for name in REGISTRY_FILES:
        body = _get(REGISTRY_URL.format(name))
        (out / "registry" / name).write_bytes(_trimmed_registry(body))
        seq = json.loads(body)["seq"]
        registry[name] = {"url": REGISTRY_URL.format(name), "seq": int(seq), "sha256": sha(body)}

    backend = lambda asset: RELEASE_URL.format(repo=BACKEND_REPO, tag=backend_release, asset=asset)
    manifest = json.loads(_get(backend("release_manifest.json")))
    record = _get(backend(FORECAST_RECORD))
    if json.loads(record)["release_tag"] != backend_release:
        raise ValueError(f"{FORECAST_RECORD} is not from {backend_release}")
    (out / FORECAST_RECORD).write_bytes(record)

    results = manifest["dependencies"]["results"]
    canonical = _get(
        RELEASE_URL.format(
            repo=results["repository"], tag=results["release"], asset=CANONICAL_ASSET
        )
    )
    rows = [
        {k: row[k] for k in CANONICAL_COLUMNS}
        for row in csv.DictReader(io.StringIO(canonical.decode("utf-8")))
        if row["election_date"] == ELECTION_DATE and row["represented_body"] in CANONICAL_BODIES
    ]
    with (out / "canonical-2026.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, CANONICAL_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    source = {
        "fetched_at": fetched_at,
        "registry": registry,
        "results": {
            "repository": results["repository"],
            "release": results["release"],
            "asset": CANONICAL_ASSET,
            "sha256": sha(canonical),
        },
        "forecast": {
            "repository": BACKEND_REPO,
            "release": backend_release,
            "asset": FORECAST_RECORD,
            "sha256": sha(record),
        },
    }
    (out / "sources.json").write_text(json.dumps(source, indent=1) + "\n", encoding="utf-8")
    return source
