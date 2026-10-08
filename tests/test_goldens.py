"""The committed golden payloads and Night Bundle are what the code emits today."""

import json
from pathlib import Path

from election_night.bundle import OPENING_2026, build_bundle, load_bundle
from election_night.goldens import goldens

ROOT = Path(__file__).parent.parent
FEED = ROOT / "tests" / "fixtures" / "feed"
GOLDENS = ROOT / "goldens" / "payload"
BUNDLE = ROOT / "data" / "night-bundle" / "night-bundle.json"

REGENERATE = "regenerate with `uv run election-night goldens`"


def test_the_committed_goldens_match_the_emitter():
    emitted = goldens(FEED)

    assert sorted(p.stem for p in GOLDENS.glob("*.json")) == sorted(emitted), REGENERATE
    for name, body in emitted.items():
        assert (GOLDENS / f"{name}.json").read_bytes() == body, f"{name}: {REGENERATE}"


def test_the_goldens_cover_every_reader_state_reachable_so_far():
    states = {
        race["state"] for body in goldens(FEED).values() for race in json.loads(body)["races"]
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
    built = build_bundle(
        (FEED / "city-2026" / "unofficialresult.json").read_bytes(),
        (FEED / "city-2026" / "unofficialresult-wardbyward.json").read_bytes(),
        opening_time=OPENING_2026,
    )

    assert load_bundle(BUNDLE) == built, "rebuild with `uv run election-night bundle`"
