"""Per-race checks and Withdrawals (#43; #17 § Per-race checks and Withdrawals, #9).

Bad data fails closed race by race, never level by level. A race whose row is unreadable or
missing has no figures; any other failed check leaves its Live Tally standing and withdraws its
projection, recording the machine reason. The mayor card's checks stay inside the ward-by-ward
file, and any ward-row failure withdraws the whole mayoral projection.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from election_night import payload as payload_module
from election_night.bundle import build_bundle
from election_night.goldens import _gate, _gated_2022, zeroed_ward_by_ward
from election_night.payload import project
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


def test_a_polls_0_row_at_a_projected_level_withdraws_only_that_race():
    def zero_polls(d):
        row(d, 3, "5")["polls"] = "0"

    body = body_of(*pair_2022(zero_polls))

    tdsb_5 = race(body, "tdsb-5")
    assert tdsb_5["state"] == "counting"
    assert tdsb_5["progress"] is None
    assert tdsb_5["projection"] is None
    assert tdsb_5["withdrawal"] == {"reason": "polls_zero"}
    assert tdsb_5["candidates"][0]["votes"] > 0
    # Per race, not per level: every other trustee area keeps its projection.
    others = [r for r in body["races"] if r["level"] == "trustee" and r["id"] != "tdsb-5"]
    assert all(r["withdrawal"] is None for r in others)
    assert any(r["projection"] for r in others if r["state"] == "counting")


def test_more_units_received_than_the_race_has_withdraws_it():
    def too_many(d):
        r = row(d, 2, "3")
        r["pollsReceived"] = str(int(r["polls"]) + 1)

    ward_3 = race(body_of(*pair_2022(too_many)), "councillor-3")

    assert ward_3["state"] == "counting"
    assert ward_3["progress"] is None
    assert ward_3["projection"] is None
    assert ward_3["withdrawal"] == {"reason": "polls_received_above_polls"}


def test_polls_that_differ_from_the_bundle_withdraw_the_race():
    def more_polls(d):
        r = row(d, 2, "7")
        r["polls"] = str(int(r["polls"]) + 1)

    ward_7 = race(body_of(*pair_2022(more_polls)), "councillor-7")

    assert ward_7["progress"] is None
    assert ward_7["projection"] is None
    assert ward_7["withdrawal"] == {"reason": "polls_differ_from_bundle"}


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

    ward_10 = race(body_of(*pair_2022(off_by_one)), "councillor-10")

    assert ward_10["progress"] is not None
    assert ward_10["projection"] is None
    assert ward_10["withdrawal"] == {"reason": "votes_received_mismatch"}
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


def test_a_ward_whose_votes_counted_is_not_its_candidates_sum_withdraws_the_mayor():
    def miscount(d):
        for c in d["office"]["candidate"]:
            entry = next(w for w in c["ward"] if w["num"] == "4")
            entry["votesCounted"] = str(int(entry["votesCounted"]) + 5)

    mayor = mayor_2023(miscount)

    assert mayor["state"] == "counting"
    assert mayor["progress"] == {"received": 1221, "total": 1451}
    assert mayor["projection"] is None
    assert mayor["withdrawal"] == {"reason": "ward_votes_counted_mismatch"}


def test_wards_that_dont_sum_to_the_office_totals_withdraw_the_mayor():
    # Chow's citywide total (and the office's) one vote above the sum of her wards.
    def citywide_extra(d):
        chow = candidate(d, "Olivia Chow")
        chow["votesReceived"] = str(int(chow["votesReceived"]) + 1)
        d["office"]["votesReceived"] = str(int(d["office"]["votesReceived"]) + 1)

    mayor = mayor_2023(citywide_extra)

    assert mayor["projection"] is None
    assert mayor["withdrawal"] == {"reason": "wards_differ_from_office"}
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

    assert mayor_2023(office_votes)["withdrawal"] == {"reason": "votes_received_mismatch"}
    zeroed = mayor_2023(office_polls)
    assert zeroed["withdrawal"] == {"reason": "polls_zero"}
    assert zeroed["progress"] is None


def test_a_ward_with_more_units_in_than_it_has_withdraws_the_mayor_and_hides_its_progress():
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

    assert mayor["withdrawal"] == {"reason": "ward_polls_received_above_polls"}
    assert mayor["progress"] == {"received": 1221, "total": 1451}
    assert mayor["projection"] is None
    ward_9 = next(w for w in mayor["wards"] if w["num"] == "9")
    assert ward_9["progress"] is None
    assert ward_9["votes_counted"] is not None
    assert mayor["possible"] is None


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

    def off_by_one(d):
        r = row(d, 2, "10")
        r["votesReceived"] = str(int(r["votesReceived"]) + 1)

    body, _ = project(edited(all_office, off_by_one), ward_by_ward, {**bundle, "gates": gates})

    assert body["levels"]["council"]["projection"] == "gate_failed"
    assert race(body, "councillor-10")["withdrawal"] == {"reason": "votes_received_mismatch"}


def test_the_mayors_ward_row_failure_withdraws_the_modelled_mayor(gated_2022):
    def miscount(d):
        for c in d["office"]["candidate"]:
            entry = next(w for w in c["ward"] if w["num"] == "4")
            entry["votesCounted"] = str(int(entry["votesCounted"]) + 5)

    body, draws = run_2022(gated_2022, edit_ward_by_ward=miscount)

    mayor = race(body, "mayor")
    assert mayor["projection"] is None
    assert mayor["withdrawal"] == {"reason": "ward_votes_counted_mismatch"}
    assert "mayor" not in draws
    assert mayor["possible"] is not None  # arithmetic on the count, not a projection
