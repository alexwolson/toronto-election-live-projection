"""Calm alerts (#17 § On the night): healthchecks pings, the reader-path probe, count decreases.

Each pipeline pings its own check after every completed tick, and pings `reader-path` only when
the public `/live/results.json` answers 200 with a heartbeat under 5 minutes old. A drop in the
citywide mayoral votes counted sends `count-decrease` its explicit fail signal; ward- and
area-level decreases are only recorded in the store, for `night status`.
"""

import json
import urllib.request
from dataclasses import dataclass

FRESH_MS = 5 * 60 * 1000  # the reader-path heartbeat must be younger than this
PING_TIMEOUT = 10
# A decrease's scope, by the payload's race level.
SCOPES = {"mayor": "citywide", "council": "ward", "trustee": "area", "french_trustee": "area"}


@dataclass(frozen=True)
class Alerts:
    """The healthchecks.io ping URLs, and the public results URL the probe reads."""

    pipeline: str  # this pipeline's check: `pipeline-fly` or `pipeline-do`
    reader_path: str
    count_decrease: str
    reader_path_url: str


def ping(url: str) -> None:
    """One ping. Errors are swallowed: a missed ping is what the check exists to notice."""
    try:
        with urllib.request.urlopen(url, timeout=PING_TIMEOUT) as response:
            response.read()
    except Exception:  # noqa: BLE001, S110
        pass


def reader_path_fresh(status: int, body: bytes, now_ms: int) -> bool:
    """True for a 200 whose served heartbeat is under 5 minutes old."""
    if status != 200:
        return False
    try:
        heartbeat = json.loads(body)["heartbeat"]
    except ValueError, TypeError, KeyError:
        return False
    if not isinstance(heartbeat, int) or isinstance(heartbeat, bool):
        return False
    return now_ms - heartbeat < FRESH_MS


def _total(race: dict) -> int | None:
    votes = [c["votes"] for c in race["candidates"]]
    if not votes or any(v is None for v in votes):
        return None
    return sum(votes)


def count_decreases(previous: dict, current: dict) -> list[dict]:
    """Every race and mayoral ward whose votes counted fell between two parsed payloads.

    A race's count is its candidates' summed votes; a mayoral ward's is its `votes_counted`.
    Each has a `scope`: `citywide` for the mayor race, `ward` for a councillor race or a mayoral
    ward, `area` for a trustee race. Races or wards without figures in either payload are skipped.
    """
    before = {race["id"]: race for race in previous["races"]}
    decreases = []
    for race in current["races"]:
        old = before.get(race["id"])
        if old is None:
            continue
        a, b = _total(old), _total(race)
        if a is not None and b is not None and b < a:
            decreases.append(
                {"scope": SCOPES[race["level"]], "race": race["id"], "before": a, "after": b}
            )
        old_wards = {ward["num"]: ward["votes_counted"] for ward in old.get("wards", [])}
        for ward in race.get("wards", []):
            a, b = old_wards.get(ward["num"]), ward["votes_counted"]
            if a is not None and b is not None and b < a:
                decreases.append(
                    {
                        "scope": "ward",
                        "race": race["id"],
                        "ward": ward["num"],
                        "before": a,
                        "after": b,
                    }
                )
    return decreases
