"""The vendored historical inputs in data/historical/ match their manifests (spec #17, S9)."""

import csv
import hashlib
from pathlib import Path

HISTORICAL = Path(__file__).resolve().parents[1] / "data" / "historical"
NON_DATA_FILES = {"SHA256SUMS", "README.md", "sources.csv", ".DS_Store"}


def _sha256sums():
    entries = {}
    for line in (HISTORICAL / "SHA256SUMS").read_text().splitlines():
        digest, path = line.split("  ", 1)
        entries[path] = digest
    return entries


def _vendored_files():
    return {
        p.relative_to(HISTORICAL).as_posix()
        for p in HISTORICAL.rglob("*")
        if p.is_file() and p.name not in NON_DATA_FILES
    }


def test_every_vendored_file_is_checksummed_and_matches():
    sums = _sha256sums()
    assert set(sums) == _vendored_files()
    for path, digest in sums.items():
        assert hashlib.sha256((HISTORICAL / path).read_bytes()).hexdigest() == digest, path


def test_every_open_data_file_has_a_source():
    # The advance-turnout table carries a source on every row instead.
    with open(HISTORICAL / "sources.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    open_data = {p for p in _vendored_files() if not p.startswith("advance_turnout/")}
    assert {row["path"] for row in rows} == open_data
    for row in rows:
        assert row["source_url"].startswith("https://"), row["path"]
        assert len(row["source_sha256"]) == 64, row["path"]


def test_advance_turnout_covers_every_replayed_night():
    with open(HISTORICAL / "advance_turnout" / "advance_turnout_as_released.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    by_year = {}
    for row in rows:
        by_year.setdefault(row["election_year"], []).append(row)
    assert set(by_year) == {"2014", "2018", "2022", "2023"}
    for year in ("2014", "2018", "2022"):
        assert [r["scope"] for r in by_year[year]] == ["city"], year
    ward_rows = [r for r in by_year["2023"] if r["scope"] == "ward"]
    city_row = next(r for r in by_year["2023"] if r["scope"] == "city")
    assert sorted(int(r["ward"]) for r in ward_rows) == list(range(1, 26))
    assert sum(int(r["advance_voters"]) for r in ward_rows) == int(city_row["advance_voters"])
    for row in rows:
        assert row["published_date"] < row["election_date"], row
        assert row["source_url"].startswith("https://"), row
