"""Per-race checks and Withdrawals (#43; #17 § Per-race checks and Withdrawals, #9).

A race whose row is unreadable or missing has no figures. Otherwise faults are tiered (#97):
- a vote-sum mismatch never withdraws: the candidates' votes stand;
- a Reporting Progress fault hides that row's progress, and the model treats its units in as
  unknown: a mayoral ward's fault stays in that ward;
- a file that contradicts itself (`ward_fields_differ`) withdraws, as do the model's own sanity
  checks.
Contained faults are returned as check notes for the operator, never shown to readers.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from election_night import payload as payload_module
from election_night.bundle import build_bundle, load_bundle
from election_night.goldens import _gate, _gated_2022, zeroed_ward_by_ward
from election_night.payload import _opening_ms, project
from election_night.projection.count_extension import RaceInputs

WAYBACK = Path(__file__).parent / "fixtures" / "feed" / "wayback"


def wayback(name: str) -> bytes:
    return (WAYBACK / name).read_bytes()


def edited(body: bytes, edit) -> bytes:
    data = json.loads(body)
    edit(data)
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def race(body: dict, race_id: str) -> dict:
    return next(r for r in body["races"] if r["id"] == race_id)


def row(data: dict, office_id: int, num: str) -> dict:
    office = next(o for o in data["office"] if o["id"] == office_id)
    return next(w for w in office["ward"] if w["num"] == num)


def add_votes(r: dict, n: int, candidate: int = 0) -> None:
    """Give a row's candidate `n` more votes, keeping the row's votesReceived consistent."""
    c = r["candidate"][candidate]
    c["votesReceived"] = str(int(c["votesReceived"]) + n)
    r["votesReceived"] = str(int(r["votesReceived"]) + n)


# --- Real files: 2022 at 21:46, and the 2023 mayor card at 20:26 --------------------------------

AO_2022_ZERO = "2022-20221025001346-all-office.json"
AO_2022_2146 = "2022-20221025014628-all-office.json"


def pair_2022(edit=None):
    all_office = wayback(AO_2022_2146)
    if edit:
        all_office = edited(all_office, edit)
    seq = int(json.loads(all_office)["seq"])
    zero = wayback(AO_2022_ZERO)
    bundle = build_bundle(zero, zeroed_ward_by_ward(zero), opening_time="2022-10-24T20:00:00-04:00")
    return all_office, zeroed_ward_by_ward(zero, seq=seq), bundle


AO_2023_ZERO = "2023-20230627000639-all-office.json"
AO_2023_2056 = "2023-20230627005628-all-office.json"
WB_2023_2026 = "2023-20230627002639-wardbyward.json"


def pair_2023(edit=None):
    ward_by_ward = wayback(WB_2023_2026)
    if edit:
        ward_by_ward = edited(ward_by_ward, edit)
    bundle = build_bundle(
        wayback(AO_2023_ZERO), wayback(WB_2023_2026), opening_time="2023-06-26T20:00:00-04:00"
    )
    return wayback(AO_2023_2056), ward_by_ward, bundle


def body_of(all_office, ward_by_ward, bundle) -> dict:
    return project(all_office, ward_by_ward, bundle)[0]


def notes_of(all_office, ward_by_ward, bundle) -> list[dict]:
    notes = []
    project(all_office, ward_by_ward, bundle, notes=notes)
    return notes


def test_clean_real_files_have_no_withdrawals():
    for body in (body_of(*pair_2022()), body_of(*pair_2023())):
        assert all(r["withdrawal"] is None for r in body["races"])
    assert race(body_of(*pair_2023()), "mayor")["projection"] is not None


def test_2022s_monavenir_polls_0_fault_hides_its_reporting_progress_only():
    # MonAvenir 4 published 539 of 0 units all night, with 411 votes and no candidates (#9).
    # Its tally stands as published; it is never projected (the French-language boards), so
    # nothing is withdrawn.
    body = body_of(*pair_2022())

    monavenir = race(body, "monavenir-4")
    assert monavenir["state"] == "counting"
    assert monavenir["progress"] is None
    assert monavenir["candidates"] == []
    assert monavenir["withdrawal"] is None
    assert race(body, "monavenir-3")["progress"] == {"received": 887, "total": 950}


def test_a_polls_0_row_at_a_projected_level_hides_its_progress_and_keeps_its_projection():
    def zero_polls(d):
        row(d, 3, "5")["polls"] = "0"

    pair = pair_2022(zero_polls)
    body = body_of(*pair)

    tdsb_5 = race(body, "tdsb-5")
    assert tdsb_5["state"] == "counting"
    assert tdsb_5["progress"] is None
    assert tdsb_5["projection"] is not None
    assert tdsb_5["withdrawal"] is None
    assert tdsb_5["candidates"][0]["votes"] > 0
    assert {"race": "tdsb-5", "reason": "polls_zero"} in notes_of(*pair)


def test_more_units_received_than_the_race_has_hides_its_progress_only():
    def too_many(d):
        r = row(d, 2, "3")
        r["pollsReceived"] = str(int(r["polls"]) + 1)

    pair = pair_2022(too_many)
    ward_3 = race(body_of(*pair), "councillor-3")

    assert ward_3["state"] == "counting"
    assert ward_3["progress"] is None
    assert ward_3["withdrawal"] is None
    assert ward_3["possible"] is not None
    assert {"race": "councillor-3", "reason": "polls_received_above_polls"} in notes_of(*pair)


def test_polls_that_differ_from_the_bundle_hide_its_progress_only():
    def more_polls(d):
        r = row(d, 2, "7")
        r["polls"] = str(int(r["polls"]) + 1)

    ward_7 = race(body_of(*pair_2022(more_polls)), "councillor-7")

    assert ward_7["progress"] is None
    assert ward_7["withdrawal"] is None


def test_all_units_in_against_polls_the_bundle_doesnt_hold_is_still_counting():
    # Every unit "in" against a polls figure the bundle doesn't hold is not "all voting areas in".
    def all_in_by_new_polls(d):
        r = row(d, 2, "7")
        r["polls"] = r["pollsReceived"]

    ward_7 = race(body_of(*pair_2022(all_in_by_new_polls)), "councillor-7")
    assert ward_7["state"] == "counting"


def test_votes_received_not_the_candidates_sum_shows_shares_from_candidate_votes():
    def off_by_one(d):
        r = row(d, 2, "10")
        r["votesReceived"] = str(int(r["votesReceived"]) + 1)

    pair = pair_2022(off_by_one)
    ward_10 = race(body_of(*pair), "councillor-10")

    assert ward_10["progress"] is not None
    assert ward_10["projection"] is not None
    assert ward_10["withdrawal"] is None
    assert {"race": "councillor-10", "reason": "votes_received_mismatch"} in notes_of(*pair)
    total = sum(c["votes"] for c in ward_10["candidates"])
    lead = ward_10["candidates"][0]
    assert lead["share"] == round(100 * lead["votes"] / total, 2)


def test_a_race_in_the_feed_but_not_in_the_bundle_is_ignored():
    def extra(d):
        office = next(o for o in d["office"] if o["id"] == 2)
        copy = json.loads(json.dumps(office["ward"][0]))
        copy["num"] = "26"
        office["ward"].append(copy)

    assert "councillor-26" not in {r["id"] for r in body_of(*pair_2022(extra))["races"]}


# --- The mayor card's checks, inside the ward-by-ward file --------------------------------------


def candidate(d: dict, name: str) -> dict:
    return next(c for c in d["office"]["candidate"] if c["name"] == name)


def ward_entry(d: dict, name: str, num: str) -> dict:
    return next(w for w in candidate(d, name)["ward"] if w["num"] == num)


def mayor_2023(edit) -> dict:
    return race(body_of(*pair_2023(edit)), "mayor")


def test_a_ward_whose_votes_counted_is_not_its_candidates_sum_keeps_the_mayor():
    def miscount(d):
        for c in d["office"]["candidate"]:
            entry = next(w for w in c["ward"] if w["num"] == "4")
            entry["votesCounted"] = str(int(entry["votesCounted"]) + 5)

    mayor = mayor_2023(miscount)

    assert mayor["state"] == "counting"
    assert mayor["progress"] == {"received": 1221, "total": 1451}
    assert mayor["projection"] is not None
    assert mayor["withdrawal"] is None
    assert mayor["possible"] is not None
    assert {"race": "mayor", "reason": "ward_votes_counted_mismatch"} in notes_of(
        *pair_2023(miscount)
    )


def test_wards_that_dont_sum_to_the_office_totals_keep_the_mayor():
    # Chow's citywide total (and the office's) one vote above the sum of her wards.
    def citywide_extra(d):
        chow = candidate(d, "Olivia Chow")
        chow["votesReceived"] = str(int(chow["votesReceived"]) + 1)
        d["office"]["votesReceived"] = str(int(d["office"]["votesReceived"]) + 1)

    mayor = mayor_2023(citywide_extra)

    assert mayor["projection"] is not None
    assert mayor["withdrawal"] is None
    clean = race(body_of(*pair_2023()), "mayor")
    votes = {c["key"]: c["votes"] for c in mayor["candidates"]}
    assert votes["Olivia Chow"] == 1 + next(
        c["votes"] for c in clean["candidates"] if c["key"] == "Olivia Chow"
    )


def test_ward_fields_that_differ_between_candidates_withdraw_the_mayor():
    def differ(d):
        entry = ward_entry(d, "Ana Bailão", "12")
        entry["pollsReceived"] = str(int(entry["pollsReceived"]) - 1)

    mayor = mayor_2023(differ)

    assert mayor["projection"] is None
    assert mayor["withdrawal"] == {"reason": "ward_fields_differ"}


def test_the_mayors_own_progress_and_votes_are_checked_like_any_race():
    def office_votes(d):
        d["office"]["votesReceived"] = str(int(d["office"]["votesReceived"]) + 1)

    def office_polls(d):
        d["office"]["polls"] = "0"

    assert mayor_2023(office_votes)["withdrawal"] is None
    zeroed = mayor_2023(office_polls)
    assert zeroed["withdrawal"] is None
    assert zeroed["progress"] is None
    assert {"race": "mayor", "reason": "polls_zero"} in notes_of(*pair_2023(office_polls))


def test_a_ward_with_more_units_in_than_it_has_hides_that_wards_progress_only():
    # Ward 9 one unit short of what it has received, ward 10 one over, so every sum still holds.
    def too_many(d):
        for c in d["office"]["candidate"]:
            for w in c["ward"]:
                if w["num"] == "9":
                    shift = int(w["polls"]) - int(w["pollsReceived"]) + 1
                    w["polls"] = str(int(w["polls"]) - shift)
            for w in c["ward"]:
                if w["num"] == "10":
                    w["polls"] = str(int(w["polls"]) + shift)

    mayor = mayor_2023(too_many)

    assert mayor["withdrawal"] is None
    assert mayor["progress"] == {"received": 1221, "total": 1451}
    ward_9 = next(w for w in mayor["wards"] if w["num"] == "9")
    assert ward_9["progress"] is None
    assert ward_9["votes_counted"] is not None
    # The ward counts as not fully reported: its remaining electors still bound it (#97).
    assert mayor["possible"] is not None
    notes = notes_of(*pair_2023(too_many))
    assert {"race": "mayor", "reason": "ward_polls_received_above_polls"} in notes
    assert {"race": "mayor", "reason": "ward_polls_differ_from_bundle"} in notes  # ward 10


# --- Checks that need a modelled night: the 2022 Replay midpoint, gated live ----------------


@pytest.fixture(scope="module")
def gated_2022():
    return _gated_2022(
        {
            "council": _gate(True),
            "trustee": _gate(True),
            "mayor-count-only": _gate(),
            "mayor-forecast-weighted": _gate(approved=True),
        }
    )


def run_2022(gated_2022, edit_all_office=None, edit_ward_by_ward=None) -> tuple[dict, dict]:
    all_office, ward_by_ward, bundle = gated_2022
    if edit_all_office:
        all_office = edited(all_office, edit_all_office)
    if edit_ward_by_ward:
        ward_by_ward = edited(ward_by_ward, edit_ward_by_ward)
    return project(all_office, ward_by_ward, bundle)


def test_the_replay_midpoint_is_projected_without_withdrawals(gated_2022):
    body, _ = run_2022(gated_2022)

    assert all(r["withdrawal"] is None for r in body["races"])
    assert race(body, "councillor-1")["projection"]["shown"] == "count_only"
    assert race(body, "mayor")["projection"]["shown"] == "forecast_weighted"


def test_a_count_above_the_top_of_the_expected_totals_grid_withdraws_the_race(gated_2022):
    _, _, bundle = gated_2022
    spec = next(r for r in bundle["races"] if r["id"] == "councillor-5")
    top = RaceInputs.from_bundle(spec["expected"]).top_total

    def past_the_top(d):
        r = row(d, 2, "5")
        add_votes(r, int(top) + 1 - int(r["votesReceived"]))

    body, draws = run_2022(gated_2022, past_the_top)

    ward_5 = race(body, "councillor-5")
    assert ward_5["progress"] is not None
    assert ward_5["projection"] is None
    assert ward_5["withdrawal"] == {"reason": "count_above_expected"}
    assert "councillor-5" not in draws
    assert race(body, "councillor-6")["projection"] is not None


def test_a_feed_name_not_in_the_bundle_keeps_count_only_and_shows_the_name(gated_2022):
    def rename(d):
        row(d, 2, "8")["candidate"][-1]["name"] = "Someone Unregistered"

    body, _ = run_2022(gated_2022, rename)

    ward_8 = race(body, "councillor-8")
    assert ward_8["withdrawal"] is None
    assert ward_8["projection"]["shown"] == "count_only"
    unknown = next(c for c in ward_8["candidates"] if c["key"] == "Someone Unregistered")
    assert unknown["full_name"] == "Someone Unregistered"
    assert unknown["short_label"] is None


def test_a_bundle_name_missing_from_the_feed_keeps_count_only(gated_2022):
    def drop(d):
        r = row(d, 2, "8")
        gone = r["candidate"].pop()
        r["votesReceived"] = str(int(r["votesReceived"]) - int(gone["votesReceived"]))

    ward_8 = race(run_2022(gated_2022, drop)[0], "councillor-8")

    assert ward_8["withdrawal"] is None
    assert ward_8["projection"]["shown"] == "count_only"


def rename_minor_mayoral(d):
    """A minor mayoral candidate renamed in every place the ward-by-ward file writes them."""
    d["office"]["candidate"][-1]["name"] = "Someone Unregistered"


def test_a_mayoral_name_mismatch_turns_the_variant_off_and_count_only_continues(gated_2022):
    body, draws = run_2022(gated_2022, edit_ward_by_ward=rename_minor_mayoral)

    mayor = race(body, "mayor")
    assert mayor["withdrawal"] is None
    assert mayor["projection"]["variant"]["off_reason"] == "forecast_unmatched"
    assert mayor["projection"]["variant"]["in_effect"] == "count_only"
    assert "count_only" in draws["mayor"] and "forecast_weighted" not in draws["mayor"]
    assert any(c["key"] == "Someone Unregistered" for c in mayor["candidates"])


def test_a_mayoral_name_mismatch_shows_count_only_when_count_only_is_live(gated_2022):
    all_office, ward_by_ward, bundle = gated_2022
    gates = {**bundle["gates"], "mayor-count-only": {**bundle["gates"]["mayor-count-only"]}}
    gates["mayor-count-only"]["pass"] = True
    body, _ = project(
        all_office, edited(ward_by_ward, rename_minor_mayoral), {**bundle, "gates": gates}
    )

    assert race(body, "mayor")["projection"]["shown"] == "count_only"


def nan_draws(real):
    def draws(*args, **kwargs):
        shares = real(*args, **kwargs)
        if shares is not None:
            shares = shares.copy()
            shares[0, 0] = np.nan
        return shares

    return draws


def test_projection_numerics_that_fail_withdraw_the_race(gated_2022, monkeypatch):
    monkeypatch.setattr(
        payload_module, "draw_final_shares", nan_draws(payload_module.draw_final_shares)
    )
    body, draws = run_2022(gated_2022)

    council = [r for r in body["races"] if r["level"] == "council" and r["state"] == "counting"]
    assert council
    for r in council:
        assert r["projection"] is None
        assert r["withdrawal"] == {"reason": "projection_numerics"}
        assert r["id"] not in draws
        assert r["candidates"][0]["votes"] is not None
    assert race(body, "mayor")["withdrawal"] is None


def test_a_band_outside_0_to_100_withdraws_the_race(gated_2022, monkeypatch):
    real = payload_module.draw_mayor_final_shares

    def above_100(*args, **kwargs):
        shares = real(*args, **kwargs)
        return None if shares is None else shares + 101.0

    monkeypatch.setattr(payload_module, "draw_mayor_final_shares", above_100)
    body, draws = run_2022(gated_2022)

    mayor = race(body, "mayor")
    assert mayor["projection"] is None
    assert mayor["withdrawal"] == {"reason": "projection_numerics"}
    assert "mayor" not in draws


def test_a_withdrawal_is_recorded_whatever_the_levels_gate(gated_2022):
    all_office, ward_by_ward, bundle = gated_2022
    gates = {**bundle["gates"], "council": {**bundle["gates"]["council"], "pass": False}}
    spec = next(r for r in bundle["races"] if r["id"] == "councillor-10")
    top = RaceInputs.from_bundle(spec["expected"]).top_total

    def past_the_top(d):
        r = row(d, 2, "10")
        add_votes(r, int(top) + 1 - int(r["votesReceived"]))

    body, _ = project(edited(all_office, past_the_top), ward_by_ward, {**bundle, "gates": gates})

    assert body["levels"]["council"]["projection"] == "gate_failed"
    assert race(body, "councillor-10")["withdrawal"] == {"reason": "count_above_expected"}


def test_a_mayoral_ward_vote_mismatch_keeps_the_modelled_mayor(gated_2022):
    def miscount(d):
        for c in d["office"]["candidate"]:
            entry = next(w for w in c["ward"] if w["num"] == "4")
            entry["votesCounted"] = str(int(entry["votesCounted"]) + 5)

    clean, _ = run_2022(gated_2022)
    body, draws = run_2022(gated_2022, edit_ward_by_ward=miscount)

    mayor = race(body, "mayor")
    assert mayor["withdrawal"] is None
    assert mayor["projection"] == race(clean, "mayor")["projection"]
    assert "mayor" in draws
    assert mayor["possible"] == race(clean, "mayor")["possible"]


def mayoral_ward_polls(d: dict, num: str, delta: int) -> None:
    for c in d["office"]["candidate"]:
        for w in c["ward"]:
            if w["num"] == num:
                w["polls"] = str(int(w["polls"]) + delta)
    d["office"]["polls"] = str(int(d["office"]["polls"]) + delta)


def test_a_mayoral_wards_progress_fault_stays_in_that_ward(gated_2022):
    # Ward 3's polls one more than the bundle's: its progress is hidden and its units in are
    # unknown, but the citywide projection, the Possible Range and the badges stay (#97).
    clean, _ = run_2022(gated_2022)
    body, draws = run_2022(gated_2022, edit_ward_by_ward=lambda d: mayoral_ward_polls(d, "3", 1))

    mayor = race(body, "mayor")
    assert mayor["withdrawal"] is None
    assert next(w for w in mayor["wards"] if w["num"] == "3")["progress"] is None
    assert mayor["projection"] is not None and "mayor" in draws
    assert mayor["possible"] is not None

    def width(r):
        b = r["projection"]["bands"][r["projection"]["shown"]]
        lead = r["candidates"][0]["key"]
        return b[lead]["high"] - b[lead]["low"]

    assert width(mayor) >= width(race(clean, "mayor"))


def test_a_council_races_progress_fault_keeps_its_modelled_projection(gated_2022):
    def more_polls(d):
        r = row(d, 2, "7")
        r["polls"] = str(int(r["polls"]) + 1)

    body, draws = run_2022(gated_2022, more_polls)

    ward_7 = race(body, "councillor-7")
    assert ward_7["withdrawal"] is None
    assert ward_7["progress"] is None
    assert ward_7["projection"] is not None and "councillor-7" in draws


# --- The French-language boards' Possible Range, from each row's own electors (#97) ---------

CITY_2026 = Path(__file__).parent / "fixtures" / "feed" / "city-2026"
NIGHT_BUNDLE = Path(__file__).parent.parent / "data" / "night-bundle" / "night-bundle.json"


def french_2026(voters: str) -> dict:
    """The City's 2026 test files, restamped after the opening, with Viamonde 3 counting: 100
    units in, 300 votes, `voters` electors on its own row."""
    bundle = load_bundle(NIGHT_BUNDLE)
    seq = str(_opening_ms(bundle) + 60_000)

    def counting(d):
        d["seq"] = seq
        r = row(d, 5, "3")
        r["pollsReceived"] = "100"
        r["totalVoters"] = voters
        for c, votes in zip(r["candidate"], (200, 100)):
            c["votesReceived"] = str(votes)
        r["votesReceived"] = "300"

    all_office = edited((CITY_2026 / "unofficialresult.json").read_bytes(), counting)
    ward_by_ward = edited(
        (CITY_2026 / "unofficialresult-wardbyward.json").read_bytes(), lambda d: d.update(seq=seq)
    )
    return race(body_of(all_office, ward_by_ward, bundle), "viamonde-3")


def test_a_french_board_gets_a_possible_range_from_its_rows_electors():
    viamonde_3 = french_2026("2500")
    assert viamonde_3["state"] == "counting"
    assert viamonde_3["projection"] is None
    lead = viamonde_3["candidates"][0]
    # 300 counted of 2,500 electors: the leader's high takes all 2,200 outstanding votes.
    assert viamonde_3["possible"][lead["key"]] == {
        "low": round(100 * lead["votes"] / 2_500, 2),
        "high": round(100 * (lead["votes"] + 2_200) / 2_500, 2),
    }


@pytest.mark.parametrize("voters", ["0", "299", "99999999"])
def test_a_french_rows_implausible_electors_give_no_possible_range(voters):
    # None; fewer than the votes counted; more than every elector of the City wards it covers.
    assert french_2026(voters)["possible"] is None
