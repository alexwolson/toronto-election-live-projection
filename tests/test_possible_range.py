"""The Possible Range (ADR 0002): each candidate's final share still mathematically possible,
from none of the outstanding votes going to them up to all of them. The outstanding votes are
bounded by every remaining elector: the City wards' electors in the bundle, less the votes
counted, floored at 0. Worked examples on the City's 2026 test files, whose wards hold
78,411 (Ward 1), 97,554 (Ward 2) and 2,143,771 electors in all.
"""

import json
from pathlib import Path

from election_night.bundle import build_bundle
from election_night.payload import project

CITY_2026 = Path(__file__).parent / "fixtures" / "feed" / "city-2026"
OPEN = "2026-01-01T00:00:00-04:00"  # before the test files' seq, so the payload is in results
TDSB_1 = {(3, "1"): (1, 7)}  # TDSB area 1 covers City wards 1 and 7 (73,832 electors)


def files():
    return (
        json.loads((CITY_2026 / "unofficialresult.json").read_text()),
        json.loads((CITY_2026 / "unofficialresult-wardbyward.json").read_text()),
    )


def dumps(data) -> bytes:
    return json.dumps(data).encode()


def bundle():
    a, w = files()
    return build_bundle(dumps(a), dumps(w), opening_time=OPEN, trustee_wards=TDSB_1)


def count_row(a: dict, office_id: int, num: str, received: int, votes: dict[str, int]) -> None:
    office = next(o for o in a["office"] if o["id"] == office_id)
    row = next(r for r in office["ward"] if r["num"] == num)
    row["pollsReceived"] = str(received)
    for c in row["candidate"]:
        c["votesReceived"] = str(votes.get(c["name"], 0))
    row["votesReceived"] = str(sum(votes.values()))


def count_mayor(w: dict, wards: dict[str, tuple[int | None, dict[str, int]]]) -> None:
    """Set each listed ward's units in (None: all) and votes, in every candidate's repeat."""
    office = w["office"]
    for num, (received, votes) in wards.items():
        for c in office["candidate"]:
            row = next(r for r in c["ward"] if r["num"] == num)
            row["pollsReceived"] = row["polls"] if received is None else str(received)
            row["votesCounted"] = str(sum(votes.values()))
            row["votesReceived"] = str(votes.get(c["name"], 0))
    totals: dict[str, int] = {}
    for votes in (v for _, v in wards.values()):
        for name, n in votes.items():
            totals[name] = totals.get(name, 0) + n
    for c in office["candidate"]:
        c["votesReceived"] = str(totals.get(c["name"], 0))
    first = office["candidate"][0]["ward"]
    office["pollsReceived"] = str(sum(int(r["pollsReceived"]) for r in first))
    office["votesReceived"] = str(sum(totals.values()))


def race(body, race_id):
    return next(r for r in body["races"] if r["id"] == race_id)


def test_a_council_race_ranges_from_none_to_all_of_its_wards_remaining_electors():
    a, w = files()
    names = [
        c["name"] for c in next(o for o in a["office"] if o["id"] == 2)["ward"][0]["candidate"]
    ]
    count_row(a, 2, "1", 10, {names[0]: 6_000, names[1]: 4_000})
    body, _ = project(dumps(a), dumps(w), bundle())
    possible = race(body, "councillor-1")["possible"]

    # 10,000 counted of 78,411 electors: up to 68,411 still to come.
    assert possible[names[0]] == {"low": 7.65, "high": 94.9}
    assert possible[names[1]] == {"low": 5.1, "high": 92.35}
    assert possible[names[2]] == {"low": 0.0, "high": 87.25}


def test_a_trustee_area_takes_the_electors_of_every_city_ward_it_covers():
    a, w = files()
    count_row(a, 3, "1", 12, {"Rosemarie Bryan": 3_000, "Antonius Clarke": 2_000})
    body, _ = project(dumps(a), dumps(w), bundle())
    possible = race(body, "tdsb-1")["possible"]

    # Wards 1 and 7: 152,243 electors, 5,000 counted.
    assert possible["Rosemarie Bryan"] == {"low": 1.97, "high": 98.69}
    assert possible["Antonius Clarke"] == {"low": 1.31, "high": 98.03}


def test_the_mayor_counts_only_the_electors_of_wards_not_fully_reported():
    a, w = files()
    x, y = (c["name"] for c in w["office"]["candidate"][:2])
    count_mayor(
        w,
        {
            "1": (20, {x: 6_000, y: 4_000}),  # 10,000 of 78,411 in: 68,411 to come
            "2": (None, {x: 10_000, y: 20_000}),  # fully reported: nothing to come
        },
    )
    body, _ = project(dumps(a), dumps(w), bundle())
    possible = race(body, "mayor")["possible"]

    # 68,411 + the 23 untouched wards' 1,967,806 = 2,036,217 to come; 40,000 counted.
    assert possible[x] == {"low": 0.77, "high": 98.84}
    assert possible[y] == {"low": 1.16, "high": 99.23}


def test_a_race_not_counting_or_without_electors_has_no_possible_range():
    a, w = files()
    body, _ = project(dumps(a), dumps(w), bundle())
    assert race(body, "councillor-1")["possible"] is None  # nothing counted yet

    count_row(a, 3, "2", 5, {"Rosemarie Bryan": 100})  # TDSB 2 has no crosswalk in this bundle
    body, _ = project(dumps(a), dumps(w), bundle())
    assert race(body, "tdsb-2")["possible"] is None

    count_row(a, 2, "1", 10, {"Abraham Abbey": 100})
    no_electors = {**bundle(), "electors": None}
    body, _ = project(dumps(a), dumps(w), no_electors)
    assert race(body, "councillor-1")["possible"] is None


def test_the_remaining_electors_never_go_below_zero():
    a, w = files()
    names = [
        c["name"] for c in next(o for o in a["office"] if o["id"] == 2)["ward"][0]["candidate"]
    ]
    count_row(a, 2, "1", 10, {names[0]: 80_000})  # more votes than the list's 78,411 electors
    body, _ = project(dumps(a), dumps(w), bundle())

    assert race(body, "councillor-1")["possible"][names[0]] == {"low": 100.0, "high": 100.0}


def test_the_feeds_ward_total_voters_is_each_wards_registered_electors():
    # ADR 0002 bounds the outstanding votes by totalVoters: check it means electors. 2018's
    # capture equals the City's voter statistics in every ward; 2023's is within 2% (the
    # statistics, published after, run slightly higher).
    from election_night.projection.history import ward_electors

    wayback = Path(__file__).parent / "fixtures" / "feed" / "wayback"
    for year, name, tolerance in (
        (2018, "2018-20181029172755-wardbyward.json", 0.0),
        (2023, "2023-20230627002639-wardbyward.json", 0.02),
    ):
        office = json.loads((wayback / name).read_text())["office"]
        feed = {int(w["num"]): int(w["totalVoters"]) for w in office["candidate"][0]["ward"]}
        stats = ward_electors(year)
        assert sorted(feed) == sorted(stats)
        for ward, electors in feed.items():
            assert abs(electors / stats[ward] - 1) <= tolerance, (year, ward)
