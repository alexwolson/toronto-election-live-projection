"""The vendored inputs the Night Bundle names its 2026 candidates from (#16).

`fetch_name_inputs` writes them to `data/night-bundle/inputs/`: the City registry, trimmed to its
name fields; the forecast's `mayoral_forecast.json` from the pinned Backend release; and the 2026
candidacies from the Results release that forecast was built from. `sources.json` records where
each came from. `load_name_inputs` reads them back for the bundle build and records the sha256 of
each file it read.
"""

import csv
import hashlib
import io
import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from election_night.names import (
    CITY_COUNCIL,
    SCHOOL_BOARDS,
    NameInputs,
    canonical_races,
    registry_races,
)

REGISTRY_URL = "https://www.toronto.ca/data/elections/candidate_list/{}"
REGISTRY_FILES = (
    "mayorCandidates_2026.json",
    "councilorCandidates_2026.json",
    "trusteeCandidates_2026.json",
)
RELEASE_URL = "https://github.com/{repo}/releases/download/{tag}/{asset}"
BACKEND_REPO = "alexwolson/toronto-election-poll-tracker-backend"
FORECAST = "mayoral_forecast.json"
CANONICAL_ASSET = "election_results.csv"
CANONICAL = "canonical-2026.csv"
SOURCES = "sources.json"
ELECTION_DATE = "2026-10-26"
CANONICAL_COLUMNS = (
    "candidacy_id",
    "person_id",
    "office_type",
    "represented_body",
    "official_district_id",
    "candidate_name",
)
REGISTRY_FIELDS = ("name", "office", "status", "firstName", "lastName")


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def forecast_ids(forecast: dict) -> list[str]:
    """The forecast's leader and challenger: the margin the mayor's variant weights by."""
    margin = forecast["election_day"]["pairwise_margin"]
    return [margin["leader_candidate_id"], margin["challenger_candidate_id"]]


def load_name_inputs(directory: Path) -> NameInputs:
    """The vendored name inputs. Fails if a registry file's `seq` isn't the one fetched."""
    source = json.loads((directory / SOURCES).read_text(encoding="utf-8"))
    bodies = {name: (directory / "registry" / name).read_bytes() for name in REGISTRY_FILES}
    for name, body in bodies.items():
        if int(json.loads(body)["seq"]) != source["registry"][name]["seq"]:
            raise ValueError(f"{name}: seq differs from {SOURCES}")
    canonical_body = (directory / CANONICAL).read_bytes()
    forecast_body = (directory / FORECAST).read_bytes()
    read = {f"registry/{name}": _sha256(body) for name, body in bodies.items()}
    read |= {CANONICAL: _sha256(canonical_body), FORECAST: _sha256(forecast_body)}
    return NameInputs(
        registry=registry_races(*bodies.values()),
        canonical=canonical_races(list(csv.DictReader(io.StringIO(canonical_body.decode())))),
        forecast_ids=forecast_ids(json.loads(forecast_body)),
        source={**source, "vendored_sha256": read},
    )


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def _trimmed_registry(body: bytes) -> bytes:
    """The registry file with only its layout, `seq` and each candidate's name fields."""

    def trim(value):
        if isinstance(value, list):
            return [trim(v) for v in value]
        if not isinstance(value, dict):
            return value
        if "firstName" in value or "lastName" in value:
            return {k: value[k] for k in REGISTRY_FIELDS if k in value}
        return {k: trim(v) for k, v in value.items() if k != "spaces"}

    return (json.dumps(trim(json.loads(body)), ensure_ascii=False, indent=1) + "\n").encode()


def _backend_asset(release: str, asset: str) -> bytes:
    return _get(RELEASE_URL.format(repo=BACKEND_REPO, tag=release, asset=asset))


def _fetch_forecast(backend_release: str, results_release: str | None = None) -> tuple:
    """The release's forecast, checked against its manifest, and the manifest.

    With `results_release`, also fails unless the forecast was built from that Results release.
    Nothing is written, so a rejected forecast never replaces the vendored one.
    """
    manifest = json.loads(_backend_asset(backend_release, "release_manifest.json"))
    forecast = _backend_asset(backend_release, FORECAST)
    published = {a["filename"]: a["sha256"] for a in manifest["assets"]}
    if published.get(FORECAST) != _sha256(forecast):
        raise ValueError(f"{FORECAST} does not match {backend_release}'s manifest")
    built_from = manifest["dependencies"]["results"]["release"]
    if results_release is not None and built_from != results_release:
        raise ValueError(f"{backend_release} was built from {built_from}, not {results_release}")
    return forecast, manifest


def _forecast_source(backend_release: str, forecast: bytes) -> dict:
    record = {"repository": BACKEND_REPO, "release": backend_release, "asset": FORECAST}
    return {**record, "sha256": _sha256(forecast)}


def _write_sources(out: Path, source: dict) -> None:
    (out / SOURCES).write_text(json.dumps(source, indent=1) + "\n", encoding="utf-8")


def fetch_name_inputs(backend_release: str, out: Path) -> dict:
    """Vendor the registry, the forecast and its Results release's 2026 candidacies."""
    (out / "registry").mkdir(parents=True, exist_ok=True)
    registry = {}
    for name in REGISTRY_FILES:
        body = _get(REGISTRY_URL.format(name))
        (out / "registry" / name).write_bytes(_trimmed_registry(body))
        seq = int(json.loads(body)["seq"])
        registry[name] = {"url": REGISTRY_URL.format(name), "seq": seq, "sha256": _sha256(body)}

    forecast, manifest = _fetch_forecast(backend_release)
    (out / FORECAST).write_bytes(forecast)
    results = manifest["dependencies"]["results"]
    canonical = _get(
        RELEASE_URL.format(
            repo=results["repository"], tag=results["release"], asset=CANONICAL_ASSET
        )
    )
    rows = [
        {k: row[k] for k in CANONICAL_COLUMNS}
        for row in csv.DictReader(io.StringIO(canonical.decode("utf-8")))
        if row["election_date"] == ELECTION_DATE
        and (row["represented_body"] == CITY_COUNCIL or row["represented_body"] in SCHOOL_BOARDS)
    ]
    with (out / CANONICAL).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, CANONICAL_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    source = {
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "registry": registry,
        "results": {
            "repository": results["repository"],
            "release": results["release"],
            "asset": CANONICAL_ASSET,
            "sha256": _sha256(canonical),
        },
        "forecast": _forecast_source(backend_release, forecast),
    }
    _write_sources(out, source)
    return source


def refresh_forecast(backend_release: str, out: Path) -> dict:
    """The forecast-only refresh: a new forecast, never new names (#16).

    Fails if the new forecast was built from a different Results release than the vendored
    candidacies, since its ids could then mean other candidacies.
    """
    source = json.loads((out / SOURCES).read_text(encoding="utf-8"))
    forecast, _ = _fetch_forecast(backend_release, source["results"]["release"])
    (out / FORECAST).write_bytes(forecast)
    source = {**source, "forecast": _forecast_source(backend_release, forecast)}
    _write_sources(out, source)
    return source
