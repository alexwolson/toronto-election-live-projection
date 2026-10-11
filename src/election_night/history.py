"""The count history: one compact entry per stored count, for the page's Count and Map views.

The store appends an entry in the same script that stores its payload, so each stored seq pair
has exactly one entry whichever pipeline stored it (docs/store.md). An entry keeps what the
over-the-count charts draw: each race's Reporting Progress, its votes, and the band the page
showed and which variant it was; for the mayor, each ward's progress. Ward votes stay in the current payload only: they
are most of a payload's bytes and no chart draws them over time. Outside the model version.
"""

import json


def _shown(race: dict) -> str | None:
    projection = race.get("projection")
    return projection.get("shown") if projection else None


def _band(race: dict, shown: str) -> dict:
    return {
        k: [b["low"], b["mid"], b["high"]] for k, b in race["projection"]["bands"][shown].items()
    }


def _progress(progress: dict | None) -> list[int] | None:
    return [progress["received"], progress["total"]] if progress else None


def history_entry(payload: dict) -> bytes | None:
    """The entry for a payload, or None before results, when there's no count to record."""
    if payload["state"] != "results":
        return None
    races = {}
    for race in payload["races"]:
        entry = {
            "p": _progress(race["progress"]),
            "v": {c["key"]: c["votes"] for c in race["candidates"] if c["votes"] is not None},
        }
        if shown := _shown(race):
            # The variant too, so the route can drop the band when its switch is off.
            entry["b"], entry["s"] = _band(race, shown), shown
        if race.get("wards") is not None:
            entry["w"] = {w["num"]: _progress(w["progress"]) for w in race["wards"]}
        races[race["id"]] = entry
    return json.dumps({"seq": payload["seq"], "races": races}, separators=(",", ":")).encode()
