"""The payload function: both City files' bytes and the Night Bundle in, payload bytes out."""

import json
from pathlib import Path

import pytest

from election_night.bundle import OPENING_2026, build_bundle
from election_night.feed import UnreadableFile, check_status
from election_night.goldens import AFTER_OPENING_2026
from election_night.names import load_name_inputs
from election_night.payload import build_payload

FEED = Path(__file__).parent / "fixtures" / "feed"
CITY_2026 = FEED / "city-2026"
NAME_INPUTS = Path(__file__).parent.parent / "data" / "night-bundle" / "inputs"


def city_2026():
    return (
        (CITY_2026 / "unofficialresult.json").read_bytes(),
        (CITY_2026 / "unofficialresult-wardbyward.json").read_bytes(),
    )


def bundle_2026():
    return build_bundle(*city_2026(), opening_time=OPENING_2026)


def payload_of(all_office, ward_by_ward, bundle):
    return json.loads(build_payload(all_office, ward_by_ward, bundle))


def race(payload, race_id):
    return next(r for r in payload["races"] if r["id"] == race_id)


def test_the_city_test_files_give_the_before_results_state_in_ballot_order():
    payload = payload_of(*city_2026(), bundle_2026())

    assert payload["state"] == "before_results"
    mayor = race(payload, "mayor")
    assert mayor["state"] == "before_results"
    assert [c["key"] for c in mayor["candidates"][:3]] == [
        "Imad Abdulkadir",
        "Bahira Abdulsalam",
        "Chris Alexander",
    ]
    assert mayor["candidates"][0]["votes"] is None
    assert len(payload["races"]) == 1 + 25 + 12 + 12 + 3 + 2


WAYBACK = FEED / "wayback"


def wayback(name):
    return (WAYBACK / name).read_bytes()


# 2023 mayoral by-election: the ward-by-ward file at 20:26:22 (Bailão ahead) and the all-office
# file at 20:56:21 (Chow ahead). The bundle comes from the 20:06 zeroed file and the 20:26 layout.
WB_2023_2026 = "2023-20230627002639-wardbyward.json"
AO_2023_2056 = "2023-20230627005628-all-office.json"
AO_2023_ZERO = "2023-20230627000639-all-office.json"


def bundle_2023(opening_time="2023-06-26T20:00:00-04:00"):
    return build_bundle(wayback(AO_2023_ZERO), wayback(WB_2023_2026), opening_time=opening_time)


def test_live_looking_files_before_the_opening_time_stay_before_results():
    # The Sept 28 repeat: real counts, but stamped before the bundle's opening time.
    payload = payload_of(
        wayback(AO_2023_2056),
        wayback(WB_2023_2026),
        bundle_2023("2023-06-26T21:00:00-04:00"),
    )

    assert payload["state"] == "before_results"
    mayor = race(payload, "mayor")
    assert mayor["state"] == "before_results"
    assert mayor["progress"] is None
    assert all(c["votes"] is None and c["share"] is None for c in mayor["candidates"])
    assert "wards" not in mayor or all(w["votes_counted"] is None for w in mayor["wards"])


def test_either_file_before_the_opening_time_keeps_the_pair_before_results():
    # Opening at 20:30 falls between the ward-by-ward seq (20:26) and the all-office seq (20:56).
    payload = payload_of(
        wayback(AO_2023_2056),
        wayback(WB_2023_2026),
        bundle_2023("2023-06-26T20:30:00-04:00"),
    )

    assert payload["state"] == "before_results"
    assert race(payload, "mayor")["state"] == "before_results"


def test_the_mayor_card_reads_only_the_ward_by_ward_file():
    payload = payload_of(wayback(AO_2023_2056), wayback(WB_2023_2026), bundle_2023())

    assert payload["state"] == "results"
    mayor = race(payload, "mayor")
    assert mayor["state"] == "counting"
    # The 20:26 ward-by-ward figures (research 02), not the all-office file's 20:56 ones.
    assert mayor["progress"] == {"received": 1221, "total": 1451}
    leader, second = mayor["candidates"][:2]
    assert (leader["key"], leader["share"]) == ("Ana Bailão", 36.14)
    assert (second["key"], second["share"]) == ("Olivia Chow", 35.16)
    assert sum(c["votes"] for c in mayor["candidates"]) == 525703
    assert len(mayor["wards"]) == 25
    ward_1 = mayor["wards"][0]
    assert ward_1["num"] == "1"
    assert ward_1["votes_counted"] == sum(ward_1["votes"].values())


# --- Structural rejection -------------------------------------------------------------------


def edited(body: bytes, edit) -> bytes:
    data = json.loads(body)
    edit(data)
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def rename(parent, old, new):
    parent[new] = parent.pop(old)


@pytest.mark.parametrize("status", [200, 304])
def test_a_200_or_304_is_read(status):
    check_status(status)


@pytest.mark.parametrize("status", [403, 404, 429, 500, 503])
def test_any_other_status_rejects_the_file(status):
    with pytest.raises(UnreadableFile):
        check_status(status)


ALL_OFFICE_BREAKS = {
    "not JSON": lambda body: body[: len(body) // 2],
    "not UTF-8": lambda body: b"\xff" + body,
    "seq renamed": lambda b: edited(b, lambda d: rename(d, "seq", "Seq")),
    "seq missing": lambda b: edited(b, lambda d: d.pop("seq")),
    "office renamed": lambda b: edited(b, lambda d: rename(d, "office", "offices")),
    "ward renamed": lambda b: edited(b, lambda d: rename(d["office"][1], "ward", "Ward")),
    "candidate renamed": lambda b: edited(
        b, lambda d: rename(d["office"][2]["ward"][0], "candidate", "candidates")
    ),
}

WARD_BY_WARD_BREAKS = {
    "not JSON": lambda body: b"<html>Service Unavailable</html>",
    "seq renamed": lambda b: edited(b, lambda d: rename(d, "seq", "sequence")),
    "office not an object": lambda b: edited(b, lambda d: d.update(office=[d["office"]])),
    "candidate renamed": lambda b: edited(b, lambda d: rename(d["office"], "candidate", "cand")),
    "ward renamed": lambda b: edited(
        b, lambda d: rename(d["office"]["candidate"][3], "ward", "wards")
    ),
}


@pytest.mark.parametrize("break_", ALL_OFFICE_BREAKS.values(), ids=ALL_OFFICE_BREAKS.keys())
def test_an_unreadable_all_office_file_rejects_the_pair(break_):
    all_office, ward_by_ward = city_2026()
    with pytest.raises(UnreadableFile):
        build_payload(break_(all_office), ward_by_ward, bundle_2026())


@pytest.mark.parametrize("break_", WARD_BY_WARD_BREAKS.values(), ids=WARD_BY_WARD_BREAKS.keys())
def test_an_unreadable_ward_by_ward_file_rejects_the_pair(break_):
    all_office, ward_by_ward = city_2026()
    with pytest.raises(UnreadableFile):
        build_payload(all_office, break_(ward_by_ward), bundle_2026())


def test_an_unreadable_row_does_not_reject_the_pair():
    # A count that isn't a string of digits spoils only its own race.
    def spoil(d):
        d["office"][1]["ward"][13]["pollsReceived"] = 12

    all_office, ward_by_ward = live_2026()
    payload = payload_of(edited(all_office, spoil), ward_by_ward, bundle_2026())

    ward_14 = race(payload, "councillor-14")
    assert ward_14["state"] == "no_figures"
    assert ward_14["fault"] == {"reason": "row_unreadable"}
    assert ward_14["withdrawal"] is None
    assert race(payload, "councillor-13")["state"] == "no_units_in"


def test_a_race_missing_from_the_feed_has_no_figures():
    all_office, ward_by_ward = live_2026()
    payload = payload_of(
        edited(all_office, lambda d: d["office"][2]["ward"].pop(4)), ward_by_ward, bundle_2026()
    )

    assert race(payload, "tdsb-5")["state"] == "no_figures"
    assert race(payload, "tdsb-5")["fault"] == {"reason": "race_missing"}


def test_a_race_in_the_feed_but_not_the_bundle_is_ignored():
    def add_ward(d):
        extra = json.loads(json.dumps(d["office"][1]["ward"][0]))
        extra["num"] = "26"
        d["office"][1]["ward"].append(extra)

    all_office, ward_by_ward = live_2026()
    payload = payload_of(edited(all_office, add_ward), ward_by_ward, bundle_2026())

    assert "councillor-26" not in {r["id"] for r in payload["races"]}


# --- Race states ----------------------------------------------------------------------------


def live_2026():
    """The City's zeroed test files, restamped one minute after the 2026 opening time."""
    return tuple(
        edited(body, lambda d: d.update(seq=str(AFTER_OPENING_2026))) for body in city_2026()
    )


def test_a_zeroed_file_after_the_opening_time_shows_no_units_in():
    payload = payload_of(*live_2026(), bundle_2026())

    assert payload["state"] == "results"
    for r in payload["races"]:
        if r["id"] not in ACCLAIMED_2026:
            assert r["state"] == "no_units_in", r["id"]
            assert r["projection"] is None
    mayor = race(payload, "mayor")
    assert mayor["progress"] == {"received": 0, "total": 1431}
    assert mayor["candidates"][0]["share"] is None


ACCLAIMED_2026 = {"tcdsb-6", "tcdsb-12", "viamonde-2", "viamonde-4"}


def test_one_candidate_races_are_acclaimed():
    payload = payload_of(*live_2026(), bundle_2026())

    assert {r["id"] for r in payload["races"] if r["state"] == "acclaimed"} == ACCLAIMED_2026
    assert race(payload, "tcdsb-6")["projection"] is None


def test_a_fully_reported_count_shows_all_units_in_without_a_projection():
    # 2018's final pair: every race at pollsReceived == polls.
    all_office = wayback("2018-20181029172648-all-office.json")
    ward_by_ward = wayback("2018-20181029172755-wardbyward.json")
    bundle = build_bundle(all_office, ward_by_ward, opening_time="2018-10-22T20:00:00-04:00")

    payload = payload_of(all_office, ward_by_ward, bundle)

    mayor = race(payload, "mayor")
    assert mayor["state"] == "all_units_in"
    assert mayor["progress"] == {"received": 1800, "total": 1800}
    assert (mayor["candidates"][0]["key"], mayor["candidates"][0]["share"]) == ("John Tory", 63.49)
    assert {r["state"] for r in payload["races"]} <= {"all_units_in", "acclaimed"}
    assert all(r["projection"] is None for r in payload["races"])


def test_a_counting_race_carries_stub_bands_marked_as_stubs():
    payload = payload_of(wayback(AO_2023_2056), wayback(WB_2023_2026), bundle_2023())

    projection = race(payload, "mayor")["projection"]
    assert projection["stub"] is True
    assert set(projection["bands"]) == {"count_only", "forecast_weighted"}
    chow = projection["bands"]["count_only"]["Olivia Chow"]
    assert 0 <= chow["low"] <= chow["mid"] == 35.16 <= chow["high"] <= 100


# --- Counts and numbers ---------------------------------------------------------------------


def test_counts_that_go_down_are_mirrored():
    # A later generation with fewer votes for Chow citywide is published as it is.
    def fewer(d):
        d["seq"] = str(int(d["seq"]) + 60_000)
        chow = next(c for c in d["office"]["candidate"] if c["name"] == "Olivia Chow")
        chow["votesReceived"] = "100000"

    payload = payload_of(wayback(AO_2023_2056), edited(wayback(WB_2023_2026), fewer), bundle_2023())

    chow = next(c for c in race(payload, "mayor")["candidates"] if c["key"] == "Olivia Chow")
    assert chow["votes"] == 100000


def test_counts_written_as_json_numbers_are_unreadable():
    # Every number arrives as a string; a bare JSON number is not the City's format.
    def numeric(d):
        d["office"]["pollsReceived"] = 1221

    payload = payload_of(
        wayback(AO_2023_2056), edited(wayback(WB_2023_2026), numeric), bundle_2023()
    )

    assert race(payload, "mayor")["state"] == "no_figures"


def test_school_board_total_voters_are_never_read():
    def garble(d):
        for office in d["office"][2:]:
            for ward in office["ward"]:
                ward["totalVoters"] = "not a number"

    all_office, ward_by_ward = live_2026()

    assert build_payload(edited(all_office, garble), ward_by_ward, bundle_2026()) == (
        build_payload(edited(all_office, lambda d: None), ward_by_ward, bundle_2026())
    )


# --- Determinism ----------------------------------------------------------------------------


def test_the_same_inputs_give_the_same_bytes():
    inputs = (wayback(AO_2023_2056), wayback(WB_2023_2026), bundle_2023())

    assert build_payload(*inputs) == build_payload(*inputs)


def test_stub_draws_are_seeded_from_both_seqs_and_the_model_version():
    def bands(all_office, ward_by_ward, bundle):
        return race(payload_of(all_office, ward_by_ward, bundle), "mayor")["projection"]

    def later(d):
        d["seq"] = str(int(d["seq"]) + 1)

    base = bands(wayback(AO_2023_2056), wayback(WB_2023_2026), bundle_2023())
    other_bundle = {**bundle_2023(), "model_version": "stub-v0-other"}

    assert bands(edited(wayback(AO_2023_2056), later), wayback(WB_2023_2026), bundle_2023()) != base
    assert bands(wayback(AO_2023_2056), edited(wayback(WB_2023_2026), later), bundle_2023()) != base
    assert bands(wayback(AO_2023_2056), wayback(WB_2023_2026), other_bundle) != base


def test_rehearsal_in_either_election_desc_raises_the_rehearsal_flag():
    def rehearsal(d):
        d["electionDesc"] = "2026 Municipal Election REHEARSAL"

    all_office, ward_by_ward = live_2026()

    assert payload_of(all_office, ward_by_ward, bundle_2026())["rehearsal"] is False
    assert payload_of(edited(all_office, rehearsal), ward_by_ward, bundle_2026())["rehearsal"]
    assert payload_of(all_office, edited(ward_by_ward, rehearsal), bundle_2026())["rehearsal"]


def test_a_mayor_race_with_no_figures_has_no_wards():
    def numeric(d):
        d["office"]["pollsReceived"] = 1221

    payload = payload_of(
        wayback(AO_2023_2056), edited(wayback(WB_2023_2026), numeric), bundle_2023()
    )

    assert race(payload, "mayor")["wards"] == []


def test_the_payload_carries_each_candidates_names_and_ids_from_the_bundle():
    names = load_name_inputs(NAME_INPUTS)
    bundle = build_bundle(*city_2026(), opening_time=OPENING_2026, names=names)
    payload = payload_of(*city_2026(), bundle)

    chow = next(c for c in race(payload, "mayor")["candidates"] if c["key"] == "Olivia Chow")
    assert chow["full_name"] == "Olivia Chow"
    assert chow["short_label"] == "Olivia Chow"  # Braeden Chow shares the last name
    assert chow["candidacy_id"] == names.canonical["mayor"]["Olivia Chow"][0]
    assert chow["candidate_id"] == "per_a4291ca7539b53e2acc1c4f108bc73e6"
    di_francesco = race(payload, "tcdsb-1")["candidates"]
    assert {c["key"]: c["short_label"] for c in di_francesco}["Jennifer Di Francesco"] == (
        "Di Francesco"
    )
    assert all(c["candidate_id"] is None for c in race(payload, "councillor-25")["candidates"])
