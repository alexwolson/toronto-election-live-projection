"""The bundle build's Ballot Names (seam 3): the test file, registry and canonical, one to one.

Each failure case edits a copy of the vendored input files, as a changed City or canonical file
would arrive.
"""

import csv
import json
import shutil
from pathlib import Path

import pytest

from election_night.bundle import OPENING_2026, build_bundle
from election_night.name_inputs import load_name_inputs
from election_night.names import ForecastUnmatched, NameMismatch

ROOT = Path(__file__).parent.parent
CITY_2026 = ROOT / "tests" / "fixtures" / "feed" / "city-2026"
INPUTS = ROOT / "data" / "night-bundle" / "inputs"

CHOW = "per_a4291ca7539b53e2acc1c4f108bc73e6"
BRADFORD = "per_d8dfddfb642358e299f4b428292666bf"


def city_2026():
    return (
        (CITY_2026 / "unofficialresult.json").read_bytes(),
        (CITY_2026 / "unofficialresult-wardbyward.json").read_bytes(),
    )


def bundle(inputs=INPUTS, all_office=None):
    ao, wb = city_2026()
    return build_bundle(
        all_office or ao, wb, opening_time=OPENING_2026, names=load_name_inputs(inputs)
    )


def candidate(b, race_id, key):
    race = next(r for r in b["races"] if r["id"] == race_id)
    return next(c for c in race["candidates"] if c["key"] == key)


@pytest.fixture
def inputs(tmp_path):
    copy = tmp_path / "inputs"
    shutil.copytree(INPUTS, copy)
    return copy


def edit_json(path: Path, edit) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    edit(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def edit_registry(inputs: Path, name: str, edit) -> None:
    edit_json(inputs / "registry" / name, edit)


def canonical_rows(inputs: Path) -> list[dict]:
    with (inputs / "canonical-2026.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_canonical(inputs: Path, rows: list[dict]) -> None:
    with (inputs / "canonical-2026.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def set_challenger(inputs: Path, candidate_id: str) -> None:
    def edit(forecast):
        forecast["election_day"]["pairwise_margin"]["challenger_candidate_id"] = candidate_id

    edit_json(inputs / "mayoral_forecast.json", edit)


# The build fails on a one-to-one mismatch in any race.


def test_a_registry_candidate_the_test_file_lacks_fails_the_build(inputs):
    def add(data):
        ward = next(w for w in data["ward"] if w["num"] == "14")
        ward["candidate"].append({"status": "Active", "firstName": "Ann", "lastName": "Other"})

    edit_registry(inputs, "councilorCandidates_2026.json", add)

    with pytest.raises(NameMismatch, match="councillor-14.*Ann Other"):
        bundle(inputs)


def test_a_test_file_candidate_the_canonical_lacks_fails_the_build(inputs):
    rows = canonical_rows(inputs)
    write_canonical(inputs, [r for r in rows if r["candidate_name"] != "Jennifer Di Francesco"])

    with pytest.raises(NameMismatch, match="tcdsb-1.*Jennifer Di Francesco"):
        bundle(inputs)


def test_a_renamed_candidate_in_the_test_file_fails_the_build():
    ao, _ = city_2026()
    data = json.loads(ao)
    data["office"][2]["ward"][0]["candidate"][0]["name"] += "e"
    renamed = json.dumps(data, ensure_ascii=False).encode()

    with pytest.raises(NameMismatch, match="tdsb-1"):
        bundle(all_office=renamed)


def test_a_race_only_the_registry_has_fails_the_build(inputs):
    def add(data):
        candidate = {"status": "Active", "firstName": "A", "lastName": "B"}
        data["ward"].append({"num": "26", "candidate": [candidate]})

    edit_registry(inputs, "councilorCandidates_2026.json", add)

    with pytest.raises(NameMismatch, match="councillor-26"):
        bundle(inputs)


def test_a_registry_file_from_another_fetch_fails_the_build(inputs):
    edit_registry(inputs, "mayorCandidates_2026.json", lambda d: d.update(seq="1"))

    with pytest.raises(ValueError, match="seq"):
        bundle(inputs)


# Every candidate carries its candidacy_id and short label.


def test_every_candidate_in_every_race_carries_a_candidacy_id_and_a_short_label():
    b = bundle()
    candidates = [c for race in b["races"] for c in race["candidates"]]

    assert len(candidates) == 361
    assert all(c["candidacy_id"].startswith("can_") for c in candidates)
    assert all(c["short_label"] for c in candidates)


@pytest.mark.parametrize(
    ("race_id", "key", "label"),
    [
        ("tcdsb-1", "Jennifer Di Francesco", "Di Francesco"),
        ("councillor-25", "Kannan S'ree Jr", "S'ree Jr"),
        ("councillor-21", "Nisha Kumari", "Nisha Kumari"),
        ("mayor", "Olivia Chow", "Olivia Chow"),
        ("mayor", "Braeden Chow", "Braeden Chow"),
        ("mayor", "Leila Yohannes", "Leila Yohannes"),
        ("mayor", "Odessa Paloma Parker", "Parker"),
        ("councillor-17", "Hassan Mubarak Noor Mohamed", "Noor Mohamed"),
    ],
)
def test_the_short_label_is_the_registry_last_name_unless_it_repeats_in_the_race(
    race_id, key, label
):
    assert candidate(bundle(), race_id, key)["short_label"] == label


def test_a_candidate_with_no_registry_last_name_is_labelled_by_the_full_ballot_name(inputs):
    def blank(data):
        choy = next(c for c in data["candidates"] if c["lastName"] == "Choy")
        choy.update(firstName="", lastName="Logan Choy")

    edit_registry(inputs, "mayorCandidates_2026.json", blank)

    assert candidate(bundle(inputs), "mayor", "Logan Choy")["short_label"] == "Logan Choy"


# The forecast's leader and challenger carry its candidate_id.


def test_only_the_forecasts_leader_and_challenger_carry_a_candidate_id():
    ids = {
        c["key"]: c["candidate_id"]
        for race in bundle()["races"]
        for c in race["candidates"]
        if c["candidate_id"]
    }

    assert ids == {"Olivia Chow": CHOW, "Brad Bradford": BRADFORD}


def test_a_forecast_id_for_an_unlinked_candidacy_matches_by_candidacy_id(inputs):
    atkinson = next(r for r in canonical_rows(inputs) if r["candidate_name"] == "Jamie Atkinson")
    assert atkinson["person_id"] == ""  # the Backend falls back to the candidacy_id
    set_challenger(inputs, atkinson["candidacy_id"])

    b = bundle(inputs)

    assert candidate(b, "mayor", "Jamie Atkinson")["candidate_id"] == atkinson["candidacy_id"]


def test_a_forecast_id_on_no_mayoral_row_fails_the_build(inputs):
    set_challenger(inputs, "per_nobody")

    with pytest.raises(ForecastUnmatched, match="per_nobody"):
        bundle(inputs)


def test_the_bundle_records_the_name_sources_and_the_files_it_read():
    source = bundle()["source"]["names"]

    vendored = json.loads((INPUTS / "registry" / "mayorCandidates_2026.json").read_text())
    assert source["registry"]["mayorCandidates_2026.json"]["seq"] == int(vendored["seq"])
    assert len(source["registry"]["mayorCandidates_2026.json"]["sha256"]) == 64
    assert source["results"]["release"] == "results-2026-10-07.1"
    assert source["forecast"]["release"] == "backend-2026-10-07.2"
    assert sorted(source["vendored_sha256"]) == [
        "canonical-2026.csv",
        "mayoral_forecast.json",
        "registry/councilorCandidates_2026.json",
        "registry/mayorCandidates_2026.json",
        "registry/trusteeCandidates_2026.json",
    ]
