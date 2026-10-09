"""The payload: a pure function of the Count Snapshot pair and the Night Bundle.

The field layout is described in docs/payload.md and versioned by SCHEMA_VERSION. The same inputs
always give the same bytes: nothing here reads a clock, a switch or an earlier snapshot.
"""

import hashlib
import json
import random
from datetime import datetime

import numpy as np

from election_night.feed import (
    MAYOR_OFFICE_ID,
    AllOffice,
    Tally,
    UnreadableRow,
    WardByWard,
    read_all_office,
    read_ward_by_ward,
)
from election_night.projection.count_extension import (
    MayorParams,
    Params,
    RaceInputs,
    bands,
    draw_final_shares,
    draw_mayor_final_shares,
)

SCHEMA_VERSION = 1
STUB_DRAWS = 1000

# A race's draws per variant: the candidates' keys in payload order, and a (draws, candidates)
# array of final shares in points. The Replay harness scores exactly these.
Draws = dict[str, tuple[tuple[str, ...], np.ndarray]]

# The projection variants each projected level carries. Until the gated projections land, every
# variant carries deterministic stub bands, marked as stubs.
VARIANTS = {
    "mayor": ("count_only", "forecast_weighted"),
    "council": ("count_only",),
    "trustee": ("count_only",),
}


def _opening_ms(bundle: dict) -> int:
    return int(datetime.fromisoformat(bundle["opening_time"]).timestamp() * 1000)


def _share(votes: int, total: int) -> float | None:
    return round(100 * votes / total, 2) if total else None


def _candidate(entry: dict | None, key: str, votes=None, share=None) -> dict:
    entry = entry or {}
    return {
        "key": key,
        "full_name": key,
        "short_label": entry.get("short_label"),
        "candidacy_id": entry.get("candidacy_id"),
        "candidate_id": entry.get("candidate_id"),
        "votes": votes,
        "share": share,
    }


def _ranked(spec: dict, votes: dict[str, int]) -> list[str]:
    """Feed names by votes, descending; ties in ballot order, then unknown names by name."""
    ballot = {c["key"]: i for i, c in enumerate(spec["candidates"])}
    return sorted(votes, key=lambda k: (-votes[k], ballot.get(k, len(ballot)), k))


def _state(spec: dict, tally: Tally) -> str:
    if spec["acclaimed"]:
        return "acclaimed"
    if tally.polls_received == 0:
        return "no_units_in"
    if tally.polls_received == tally.polls:
        return "all_units_in"
    return "counting"


def _race(spec: dict) -> dict:
    race = {
        "id": spec["id"],
        "level": spec["level"],
        "num": spec["num"],
        "name": spec["name"],
        "state": "before_results",
        "progress": None,
        "candidates": [_candidate(c, c["key"]) for c in spec["candidates"]],
        "projection": None,
        "withdrawal": None,
        "fault": None,
    }
    if spec["office_id"] == MAYOR_OFFICE_ID:
        race["wards"] = [
            {
                "num": ward["num"],
                "name": ward["name"],
                "progress": None,
                "votes_counted": None,
                "votes": None,
            }
            for ward in spec["wards"]
        ]
    return race


def _with_tally(race: dict, spec: dict, tally: Tally) -> None:
    entries = {c["key"]: c for c in spec["candidates"]}
    total = sum(tally.votes.values())
    race["state"] = _state(spec, tally)
    race["progress"] = {"received": tally.polls_received, "total": tally.polls}
    race["candidates"] = [
        _candidate(entries.get(key), key, tally.votes[key], _share(tally.votes[key], total))
        for key in _ranked(spec, tally.votes)
    ]


def _no_figures(race: dict, reason: str) -> None:
    race["state"] = "no_figures"
    race["fault"] = {"reason": reason}
    if "wards" in race:
        race["wards"] = []


def _stub_bands(race: dict, rng: random.Random) -> dict:
    bands = {}
    for candidate in race["candidates"]:
        share = candidate["share"] or 0.0
        half = rng.uniform(0.5, 4.0)
        bands[candidate["key"]] = {
            "low": round(max(0.0, share - half), 2),
            "mid": share,
            "high": round(min(100.0, share + half), 2),
        }
    return bands


def _stub_draws(bands: dict, keys: tuple[str, ...], rng: np.random.Generator) -> np.ndarray:
    """Stub draws: each candidate's share uniform within their stub band."""
    low = np.array([bands[k]["low"] for k in keys])
    high = np.array([bands[k]["high"] for k in keys])
    return rng.uniform(low, high, size=(STUB_DRAWS, len(keys)))


def _mayor_race(race: dict, spec: dict, w: WardByWard) -> None:
    try:
        tally = w.tally()
        wards = w.wards()
    except UnreadableRow:
        _no_figures(race, "row_unreadable")
        return
    _with_tally(race, spec, tally)
    order = [c["key"] for c in race["candidates"]]
    race["wards"] = [
        {
            "num": ward.num,
            "name": ward.name,
            "progress": {"received": ward.polls_received, "total": ward.polls},
            "votes_counted": ward.votes_counted,
            "votes": {key: ward.votes[key] for key in order if key in ward.votes},
        }
        for ward in wards
    ]


def _all_office_race(race: dict, spec: dict, a: AllOffice) -> None:
    try:
        tally = a.tally(spec["office_id"], spec["num"])
    except KeyError:
        _no_figures(race, "race_missing")
        return
    except UnreadableRow:
        _no_figures(race, "row_unreadable")
        return
    _with_tally(race, spec, tally)


def _model(race: dict, spec: dict, params: dict, rng: np.random.Generator, draws: dict) -> None:
    """The count-extension projection for a counting single-unit race. Inputs that don't cover
    the race's units fail closed: the count stands with no projection."""
    inputs = RaceInputs.from_bundle(spec["expected"])
    if inputs.units != race["progress"]["total"]:
        return
    keys = tuple(c["key"] for c in race["candidates"])
    votes = np.array([c["votes"] for c in race["candidates"]])
    shares = draw_final_shares(inputs, Params(**params), votes, race["progress"]["received"], rng)
    _projected(race, keys, shares, draws)


def _projected(race: dict, keys: tuple[str, ...], shares: np.ndarray | None, draws: dict) -> None:
    """The race's count-only bands and draws, unless the model showed no projection."""
    if shares is None:
        return
    race["projection"] = {"stub": False, "bands": {"count_only": bands(shares, keys)}}
    draws[race["id"]] = {"count_only": (keys, shares)}


def _mayor_model(
    race: dict, spec: dict, params: dict, rng: np.random.Generator, draws: dict
) -> None:
    """The mayor's projection from the ward-by-ward file alone: one unit per City ward, summed
    to the citywide result. Inputs that don't match the file's wards and their units fail
    closed: the count stands with no projection."""
    inputs = RaceInputs.from_bundle(spec["expected"])
    wards = {w["num"]: w for w in race["wards"]}
    if sorted(wards) != sorted(w.ward for w in inputs.wards) or any(
        w.election_day_units + len(w.aggregates) != wards[w.ward]["progress"]["total"]
        for w in inputs.wards
    ):
        return
    keys = tuple(c["key"] for c in race["candidates"])
    votes = np.array([[wards[w.ward]["votes"].get(k, 0) for k in keys] for w in inputs.wards])
    received = np.array([wards[w.ward]["progress"]["received"] for w in inputs.wards])
    shares = draw_mayor_final_shares(inputs, MayorParams(**params), votes, received, rng)
    _projected(race, keys, shares, draws)


def _seed(a_seq: int, w_seq: int, model_version: str) -> int:
    digest = hashlib.sha256(f"{a_seq}:{w_seq}:{model_version}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def project(
    all_office: bytes, ward_by_ward: bytes, bundle: dict, only: set[str] | None = None
) -> tuple[dict, dict[str, Draws]]:
    """The payload, and the draws behind each projected race's bands, by race id and variant.

    Each modelled race draws from its own stream, seeded by the pair, the model version and its
    place in the bundle, so its draws don't depend on any other race. The Replays pass `only`,
    the races they score at this snapshot, and skip every other modelled race's projection; stub
    races are always drawn, so they never change. The night never passes it. Raises UnreadableFile if the pair is rejected.
    """
    a = read_all_office(all_office)
    w = read_ward_by_ward(ward_by_ward)
    opening = _opening_ms(bundle)
    before = a.seq < opening or w.seq < opening

    seed = _seed(a.seq, w.seq, bundle["model_version"])
    rng = random.Random(seed)
    draw_rng = np.random.default_rng(seed)
    races, draws = [], {}
    fitted = bundle.get("projection", {}).get("params", {})
    for index, spec in enumerate(bundle["races"]):
        race = _race(spec)
        if not before:
            if spec["office_id"] == MAYOR_OFFICE_ID:
                _mayor_race(race, spec, w)
            else:
                _all_office_race(race, spec, a)
            params = fitted.get(spec["level"])
            modelled = race["state"] == "counting" and params and "expected" in spec
            if modelled and (only is None or spec["id"] in only):
                race_rng = np.random.default_rng(np.random.SeedSequence([seed, index]))
                model = _mayor_model if spec["office_id"] == MAYOR_OFFICE_ID else _model
                model(race, spec, params, race_rng, draws)
            elif not modelled and race["state"] == "counting" and spec["level"] in VARIANTS:
                bands = {v: _stub_bands(race, rng) for v in VARIANTS[spec["level"]]}
                race["projection"] = {"stub": True, "bands": bands}
                keys = tuple(c["key"] for c in race["candidates"])
                draws[race["id"]] = {
                    v: (keys, _stub_draws(b, keys, draw_rng)) for v, b in bands.items()
                }
        races.append(race)

    desc = a.election_desc
    payload = {
        "schema_version": SCHEMA_VERSION,
        "model_version": bundle["model_version"],
        "forecast_release_tag": bundle["forecast_release_tag"],
        "seq": {"all_office": a.seq, "ward_by_ward": w.seq},
        "election_desc": desc,
        "rehearsal": any("REHEARSAL" in (d or "") for d in (desc, w.election_desc)),
        "state": "before_results" if before else "results",
        "levels": {
            "mayor": {"projection": "stub", "variant": "stub"},
            "council": {"projection": "stub"},
            "trustee": {"projection": "stub"},
            "french_trustee": {"projection": "none"},
        },
        "races": races,
    }
    return payload, draws


def build_payload(all_office: bytes, ward_by_ward: bytes, bundle: dict) -> bytes:
    """Build the payload bytes, or raise UnreadableFile if the pair is rejected."""
    payload, _ = project(all_office, ward_by_ward, bundle)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
