"""Calm alerts: the reader-path freshness test and count decreases between payloads."""

import json

import pytest

from election_night.alerts import count_decreases, reader_path_fresh

NOW = 10_000_000


def served(heartbeat: int) -> bytes:
    return json.dumps({"heartbeat": heartbeat, "payload": {}}).encode()


@pytest.mark.parametrize(
    ("status", "body", "fresh"),
    [
        (200, served(NOW - 299_000), True),
        (200, served(NOW - 301_000), False),
        (500, served(NOW), False),
        (304, b"", False),
        (200, b"<html>", False),
        (200, json.dumps({"payload": {}}).encode(), False),
        (200, json.dumps({"heartbeat": "soon"}).encode(), False),
    ],
)
def test_the_reader_path_is_fresh_only_on_a_200_with_a_heartbeat_under_5_minutes(
    status, body, fresh
):
    assert reader_path_fresh(status, body, NOW) is fresh


def race(race_id: str, votes: list[int | None], wards: list[tuple[str, int | None]] = ()) -> dict:
    return {
        "id": race_id,
        "level": {"mayor": "mayor", "councillor": "council", "tdsb": "trustee"}[
            race_id.split("-")[0]
        ],
        "candidates": [{"key": f"c{i}", "votes": v} for i, v in enumerate(votes)],
        "wards": [{"num": num, "votes_counted": counted} for num, counted in wards],
    }


def payload(*races: dict) -> dict:
    return {"seq": {"all_office": 1, "ward_by_ward": 1}, "races": list(races)}


def test_a_citywide_mayoral_decrease_is_citywide():
    before = payload(race("mayor", [100, 50]))
    after = payload(race("mayor", [90, 50]))
    assert count_decreases(before, after) == [
        {"scope": "citywide", "race": "mayor", "before": 150, "after": 140}
    ]


def test_ward_and_area_decreases_are_not_citywide():
    before = payload(
        race("mayor", [100], wards=[("1", 40), ("2", 60)]),
        race("councillor-3", [30, 20]),
        race("tdsb-5", [12]),
    )
    after = payload(
        race("mayor", [100], wards=[("1", 39), ("2", 61)]),
        race("councillor-3", [30, 19]),
        race("tdsb-5", [11]),
    )
    assert count_decreases(before, after) == [
        {"scope": "ward", "race": "mayor", "ward": "1", "before": 40, "after": 39},
        {"scope": "ward", "race": "councillor-3", "before": 50, "after": 49},
        {"scope": "area", "race": "tdsb-5", "before": 12, "after": 11},
    ]


def test_missing_figures_and_growth_are_not_decreases():
    before = payload(race("mayor", [100]), race("councillor-1", [10]), race("tdsb-1", [5]))
    after = payload(race("mayor", [None]), race("councillor-1", [11]))
    assert count_decreases(before, after) == []
