"""The committed golden payloads and Night Bundle are what the code emits today."""

import json
from pathlib import Path

from election_night.bundle import OPENING_2026, build_night_bundle, load_bundle
from election_night.goldens import goldens
from election_night.name_inputs import load_name_inputs

ROOT = Path(__file__).parent.parent
FEED = ROOT / "tests" / "fixtures" / "feed"
GOLDENS = ROOT / "goldens" / "payload"
BUNDLE = ROOT / "data" / "night-bundle" / "night-bundle.json"
NAME_INPUTS = ROOT / "data" / "night-bundle" / "inputs"

REGENERATE = "regenerate with `uv run election-night goldens`"


def test_the_committed_goldens_match_the_emitter():
    emitted = goldens(FEED, load_name_inputs(NAME_INPUTS))

    assert sorted(p.stem for p in GOLDENS.glob("*.json")) == sorted(emitted), REGENERATE
    for name, body in emitted.items():
        assert (GOLDENS / f"{name}.json").read_bytes() == body, f"{name}: {REGENERATE}"


def test_the_goldens_cover_every_reader_state_reachable_so_far():
    states = {
        race["state"]
        for body in goldens(FEED, load_name_inputs(NAME_INPUTS)).values()
        for race in json.loads(body)["races"]
    }

    assert states == {
        "before_results",
        "no_units_in",
        "counting",
        "all_units_in",
        "acclaimed",
        "no_figures",
    }


def test_the_committed_night_bundle_is_built_from_the_city_test_files():
    built = build_night_bundle(
        FEED / "city-2026",
        load_name_inputs(NAME_INPUTS),
        OPENING_2026,
        ROOT / "data" / "mock-feed" / "trustee_wards_2026.csv",
        ROOT / "gates",
        NAME_INPUTS / "advance_turnout_2026.json",
        bundle_dir=BUNDLE.parent,
    )

    assert load_bundle(BUNDLE) == built, "rebuild with `uv run election-night bundle`"


def test_the_2026_goldens_carry_the_ballot_names():
    body = json.loads(goldens(FEED, load_name_inputs(NAME_INPUTS))["no-units-in-2026"])
    mayor = next(r for r in body["races"] if r["id"] == "mayor")

    assert all(c["candidacy_id"] and c["short_label"] for c in mayor["candidates"])
    assert sum(1 for c in mayor["candidates"] if c["candidate_id"]) == 2
