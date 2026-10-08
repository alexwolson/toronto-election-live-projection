"""The bundle build's Ballot Names (seam 3): the test file, registry and canonical, one to one."""

import dataclasses
import json
from pathlib import Path

import pytest

from election_night.bundle import OPENING_2026, build_bundle
from election_night.names import ForecastUnmatched, NameMismatch, load_name_inputs

ROOT = Path(__file__).parent.parent
CITY_2026 = ROOT / "tests" / "fixtures" / "feed" / "city-2026"
INPUTS = ROOT / "data" / "night-bundle" / "inputs"


def city_2026():
    return (
        (CITY_2026 / "unofficialresult.json").read_bytes(),
        (CITY_2026 / "unofficialresult-wardbyward.json").read_bytes(),
    )


def bundle(all_office=None, ward_by_ward=None, names=None):
    ao, wb = city_2026()
    return build_bundle(
        all_office or ao,
        ward_by_ward or wb,
        opening_time=OPENING_2026,
        names=names or load_name_inputs(INPUTS),
    )


def candidate(b, race_id, key):
    race = next(r for r in b["races"] if r["id"] == race_id)
    return next(c for c in race["candidates"] if c["key"] == key)


def edited_names(**changes):
    return dataclasses.replace(load_name_inputs(INPUTS), **changes)


def without(races, race_id, name):
    return {r: {k: v for k, v in c.items() if k != name or r != race_id} for r, c in races.items()}


# The build fails on a one-to-one mismatch in any race.


def test_a_registry_name_the_test_file_lacks_fails_the_build():
    names = load_name_inputs(INPUTS)
    registry = {**names.registry, "councillor-14": {**names.registry["councillor-14"], "X Y": "Y"}}

    with pytest.raises(NameMismatch, match="councillor-14"):
        bundle(names=dataclasses.replace(names, registry=registry))


def test_a_test_file_name_the_canonical_lacks_fails_the_build():
    names = load_name_inputs(INPUTS)

    with pytest.raises(NameMismatch, match="tcdsb-1"):
        bundle(
            names=edited_names(
                canonical=without(names.canonical, "tcdsb-1", "Jennifer Di Francesco")
            )
        )


def test_a_renamed_candidate_in_the_test_file_fails_the_build():
    ao, _ = city_2026()
    data = json.loads(ao)
    data["office"][2]["ward"][0]["candidate"][0]["name"] += "e"
    renamed = json.dumps(data, ensure_ascii=False).encode()

    with pytest.raises(NameMismatch, match="tdsb-1"):
        bundle(all_office=renamed)


def test_a_race_only_the_registry_has_fails_the_build():
    names = load_name_inputs(INPUTS)
    registry = {**names.registry, "councillor-26": {"A B": "B"}}

    with pytest.raises(NameMismatch, match="councillor-26"):
        bundle(names=dataclasses.replace(names, registry=registry))


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


def test_a_candidate_with_no_registry_last_name_is_labelled_by_the_full_ballot_name():
    names = load_name_inputs(INPUTS)
    registry = {**names.registry, "mayor": {**names.registry["mayor"], "Logan Choy": ""}}

    b = bundle(names=dataclasses.replace(names, registry=registry))

    assert candidate(b, "mayor", "Logan Choy")["short_label"] == "Logan Choy"


# Forecast-named mayoral rows carry the forecast's candidate_id.

CHOW, BRADFORD, ALEXANDER = (
    "per_a4291ca7539b53e2acc1c4f108bc73e6",
    "per_d8dfddfb642358e299f4b428292666bf",
    "per_345dd6a9ee645c0bb5a8ade615f91579",
)


def test_each_forecast_named_candidate_id_sits_on_exactly_one_mayoral_row():
    b = bundle()
    ids = {
        c["key"]: c["candidate_id"]
        for race in b["races"]
        for c in race["candidates"]
        if c["candidate_id"]
    }

    assert ids == {"Olivia Chow": CHOW, "Brad Bradford": BRADFORD, "Chris Alexander": ALEXANDER}


def test_a_forecast_id_for_an_unlinked_candidacy_matches_by_candidacy_id():
    names = load_name_inputs(INPUTS)
    atkinson = names.canonical["mayor"]["Jamie Atkinson"]
    assert atkinson[1] is None  # no person_id: the Backend falls back to the candidacy_id

    b = bundle(names=dataclasses.replace(names, forecast_ids=[CHOW, atkinson[0]]))

    assert candidate(b, "mayor", "Jamie Atkinson")["candidate_id"] == atkinson[0]


def test_a_forecast_id_on_no_mayoral_row_fails_the_build():
    with pytest.raises(ForecastUnmatched, match="per_nobody"):
        bundle(names=edited_names(forecast_ids=[CHOW, "per_nobody"]))


def test_the_bundle_records_the_name_sources():
    source = bundle()["source"]["names"]

    assert source["registry"]["mayorCandidates_2026.json"]["seq"] == 1791427980814
    assert len(source["registry"]["mayorCandidates_2026.json"]["sha256"]) == 64
    assert source["results"]["release"] == "results-2026-10-07.1"
    assert source["forecast"]["release"] == "backend-2026-10-07.2"
