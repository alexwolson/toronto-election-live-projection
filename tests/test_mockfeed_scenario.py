"""The Mock Feed scenario (spec #17 § Testing Decisions, seam 5; ticket #34, S6).

The scenario is the invented 2026 count a Rehearsal runs against: the City's zeroed test file's
races, carried over from 2023 (mayor) and 2022 (council and trustee) by rank. Every race's `polls`
must equal the test file's, and every carried vote must be kept.
"""

import json
from pathlib import Path

import pytest

from election_night.feed import (
    COUNCILLOR_OFFICE_ID,
    MAYOR_OFFICE_ID,
    race_id,
    read_all_office,
    read_ward_by_ward,
)
from election_night.gates import load_preregistration
from election_night.mockfeed.scenario import load_scenario
from election_night.replay.historical import load_night

ROOT = Path(__file__).parent.parent
PREREG = load_preregistration(ROOT / "gates" / "preregistration.json")
CITY_2026 = ROOT / "tests" / "fixtures" / "feed" / "city-2026"


@pytest.fixture(scope="module")
def test_file():
    a = read_all_office((CITY_2026 / "unofficialresult.json").read_bytes())
    w = read_ward_by_ward((CITY_2026 / "unofficialresult-wardbyward.json").read_bytes())
    return a, w


@pytest.fixture(scope="module")
def scenario():
    return load_scenario(seed=0)


@pytest.fixture(scope="module")
def sources():
    return load_night(2023, PREREG), load_night(2022, PREREG)


@pytest.fixture(scope="module")
def final(scenario):
    return scenario.true_count(scenario.steps)


def test_every_race_has_the_test_files_reporting_units(scenario, test_file, final):
    a, w = test_file
    expected = {race_id(o, n): a.tally(o, n).polls for o, n in a.rows}
    assert {rid: t.polls for rid, t in final.races.items()} == expected
    assert {t.num: t.polls for t in final.wards} == {t.num: t.polls for t in w.wards()}
    assert scenario.steps == w.tally().polls == 1431


def _ward_votes(race, ward: int, codes=None) -> int:
    """A source race's votes in one City ward's units (only `codes`, if given)."""
    return sum(
        int(race.votes[i].sum())
        for i, (w, c) in enumerate(race.units)
        if w == ward and (codes is None or c in codes)
    )


def test_every_carried_vote_is_kept(scenario, sources, final):
    n23, n22 = sources
    by_id = {race_id(r.office_id, r.num): r for r in scenario.night.races}
    assert sum(final.races["mayor"].votes.values()) == int(n23.mayor.certified.sum()) == 724_638
    for ward in final.wards:
        assert ward.votes_counted == _ward_votes(n23.mayor, int(ward.num))
    for rid, race in by_id.items():
        if race.office_id == MAYOR_OFFICE_ID:
            continue
        total = sum(final.races[rid].votes.values())
        wards = sorted({w for w, _ in race.units})
        if race.office_id in (5, 6):  # the French boards have no workbooks: nothing is carried
            assert total == 0
            continue
        source = [r for r in n22.races if r.office_id == race.office_id]
        assert total == sum(_ward_votes(r, w) for r in source for w in wards), rid
    assert sum(sum(final.races[f"councillor-{w}"].votes.values()) for w in range(1, 26)) == 539_312


def test_ward_aggregates_keep_their_size(scenario, sources):
    n23, n22 = sources
    codes = PREREG["arrival_orders"]["ward_aggregates"]["codes"]
    for race in scenario.night.races:
        source = n23.mayor if race.office_id == MAYOR_OFFICE_ID else None
        if race.office_id == COUNCILLOR_OFFICE_ID:
            source = next(
                r for r in n22.races if r.office_id == COUNCILLOR_OFFICE_ID and r.num == race.num
            )
        if source is None:
            continue
        for ward in sorted({w for w, _ in race.units}):
            for code in codes:
                assert _ward_votes(race, ward, [code]) == _ward_votes(source, ward, [code])


def test_mayor_takes_2023_by_the_forecasts_rank(final):
    # 2023's top three (Chow 269,372, Bailão 235,175, Saunders 62,167) go to the forecast's
    # top three (Chow, Bradford, Alexander).
    votes = final.races["mayor"].votes
    assert votes["Olivia Chow"] == 269_372
    assert votes["Brad Bradford"] == 235_175
    assert votes["Chris Alexander"] == 62_167


def test_council_takes_2022_by_rank_in_the_test_files_order(test_file, final):
    a, _ = test_file
    # Ward 2: three 2026 candidates, five in 2022 (18,559, 2,653, 2,318, 1,591, 557); the last
    # folds in 2022's third to fifth.
    ward2 = list(final.races["councillor-2"].votes.values())
    assert list(final.races["councillor-2"].votes) == list(a.tally(2, "2").votes)
    assert ward2 == [18_559, 2_653, 2_318 + 1_591 + 557]
    # Ward 14: eighteen 2026 candidates, five in 2022; the other thirteen get 0.
    ward14 = list(final.races["councillor-14"].votes.values())
    assert ward14 == [20_305, 1_982, 1_937, 1_740, 1_469] + [0] * 13


def test_the_scenario_is_deterministic_for_a_seed(scenario):
    again, other = load_scenario(seed=0), load_scenario(seed=1)
    assert again.order.tolist() == scenario.order.tolist()
    assert other.order.tolist() != scenario.order.tolist()
    for step in (0, 700, scenario.steps):
        assert again.true_count(step) == scenario.true_count(step)


def test_the_true_count_runs_from_zero_to_the_final_count(scenario, final):
    zero = scenario.true_count(0)
    assert all(t.polls_received == 0 and not any(t.votes.values()) for t in zero.races.values())
    assert all(t.polls_received == t.polls for t in final.races.values())
    received = [
        scenario.true_count(s).races["mayor"].polls_received
        for s in range(0, scenario.steps + 1, 13)
    ]
    assert received == sorted(received)
    for step in (1, 400, scenario.steps):
        count = scenario.true_count(step)
        mayor = count.races["mayor"]
        assert sum(t.polls_received for t in count.wards) == mayor.polls_received == step
        for name, votes in mayor.votes.items():
            assert sum(t.votes[name] for t in count.wards) == votes
        council = sum(sum(count.races[f"councillor-{w}"].votes.values()) for w in range(1, 26))
        assert council <= 539_312


def test_bradford_leads_on_election_day_and_chow_wins_on_the_late_ward_aggregates(scenario):
    # The "late" pattern sends every Ward Aggregate after 85% of the 1,356 election-day units.
    early = scenario.true_count(1_000).races["mayor"].votes
    assert early["Brad Bradford"] > early["Olivia Chow"]
    final = scenario.true_count(scenario.steps).races["mayor"].votes
    assert final["Olivia Chow"] > final["Brad Bradford"]


def test_each_step_is_a_city_shaped_count_snapshot_pair_reading_as_the_true_count(scenario):
    template = json.loads((CITY_2026 / "unofficialresult.json").read_bytes())
    template_voters = {
        race_id(o["id"], r["num"]): r["totalVoters"] for o in template["office"] for r in o["ward"]
    }
    for step in (0, 700, scenario.steps):
        all_office, ward_by_ward = scenario.count_snapshot(step)
        a, w = read_all_office(all_office), read_ward_by_ward(ward_by_ward)
        truth = scenario.true_count(step)
        assert {race_id(o, n): a.tally(o, n) for o, n in a.rows} == truth.races
        assert w.tally() == truth.races["mayor"]
        assert w.wards() == truth.wards
        data = json.loads(all_office)
        assert {
            race_id(o["id"], r["num"]): r["totalVoters"] for o in data["office"] for r in o["ward"]
        } == template_voters
        for office in data["office"]:
            for row in office["ward"]:
                votes = [int(c["votesReceived"]) for c in row["candidate"]]
                assert votes == sorted(votes, reverse=True)
                assert all(isinstance(v, str) for c in row["candidate"] for v in c.values())
