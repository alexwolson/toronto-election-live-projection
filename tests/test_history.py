"""The count history: one compact entry per stored count, for the page's Count and Map views."""

import json

from election_night.history import history_entry


def race(**overrides) -> dict:
    return {
        "id": "councillor-4",
        "level": "council",
        "state": "counting",
        "progress": {"received": 10, "total": 40},
        "candidates": [
            {"key": "B", "votes": 300, "share": 60.0},
            {"key": "A", "votes": 200, "share": 40.0},
        ],
        "projection": None,
        "withdrawal": None,
        **overrides,
    }


def payload(races: list[dict], state: str = "results") -> dict:
    return {"seq": {"all_office": 5, "ward_by_ward": 6}, "state": state, "races": races}


def entry(p: dict) -> dict:
    return json.loads(history_entry(p))


def test_an_entry_holds_the_seq_and_each_race_s_progress_and_votes():
    assert entry(payload([race()])) == {
        "seq": {"all_office": 5, "ward_by_ward": 6},
        "races": {"councillor-4": {"p": [10, 40], "v": {"B": 300, "A": 200}}},
    }


def test_only_the_shown_band_is_kept_as_low_mid_high():
    projection = {
        "stub": False,
        "bands": {
            "count_only": {"B": {"low": 50.0, "mid": 58.0, "high": 66.0}},
            "forecast_weighted": {"B": {"low": 52.0, "mid": 57.0, "high": 61.0}},
        },
        "shown": "forecast_weighted",
    }
    got = entry(payload([race(projection=projection)]))["races"]["councillor-4"]
    assert got["b"] == {"B": [52.0, 57.0, 61.0]}


def test_no_band_when_none_is_shown_or_the_projection_is_withdrawn():
    hidden = {
        "stub": False,
        "bands": {"count_only": {"B": {"low": 1, "mid": 2, "high": 3}}},
        "shown": None,
    }
    withdrawn = race(projection=None, withdrawal={"reason": "progress_regressed"})
    got = entry(payload([race(projection=hidden), {**withdrawn, "id": "tdsb-5"}]))["races"]
    assert "b" not in got["councillor-4"] and "b" not in got["tdsb-5"]


def test_the_mayor_keeps_each_ward_s_progress_but_not_its_votes():
    wards = [
        {"num": "1", "progress": {"received": 3, "total": 50}, "votes": {"B": 9}},
        {"num": "2", "progress": None, "votes": None},
    ]
    got = entry(payload([race(id="mayor", level="mayor", wards=wards)]))["races"]["mayor"]
    assert got["w"] == {"1": [3, 50], "2": None}


def test_a_race_without_figures_keeps_null_progress_and_no_votes():
    blank = race(progress=None, candidates=[{"key": "A", "votes": None, "share": None}])
    assert entry(payload([blank]))["races"]["councillor-4"] == {"p": None, "v": {}}


def test_before_results_there_is_no_entry():
    assert history_entry(payload([race()], state="before_results")) is None


def test_the_entry_is_compact_json():
    assert b" " not in history_entry(payload([race()]))
