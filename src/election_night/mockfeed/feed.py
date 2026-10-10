"""The Mock Feed's responses: the scenario served as the City serves its two files (#37).

Each response is a pure function of the scenario, start time, speed, clock and request. The start
maps to 19:50 EDT on Oct 26 and the night clock runs at `speed`. Each file is generated once a
night minute, the ward-by-ward file 20 ms before the all-office one (as in the City's test files),
until the count is complete; then its last `seq` stays frozen. Units arrive on 2023's observed
curve from 20:00. From 19:50 the first minutes repeat the Sept 28 incident: live-looking data,
then the files regenerated as zeros at 20:00. Every file says REHEARSAL in `electionDesc`.

The faults are scheduled on the night clock; `faults=()` turns them off. Plumbing serves `FAULTS`,
the HTTP faults. The Full night serves `FULL_NIGHT`, which adds the data faults: each changes the
files generated in its night minutes, so it lands in the bytes and in `reference`. It also holds
back the last units for a near-silent tail (`FULL_NIGHT_TAIL`), regenerating the files only as
each arrives. docs/full-night-faults.md lists each fault's expected reader state.
"""

import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from email.utils import formatdate
from functools import lru_cache

import numpy as np

from election_night.feed import COUNCILLOR_OFFICE_ID, MAYOR_OFFICE_ID, race_id
from election_night.mockfeed.scenario import Scenario, fill_row
from election_night.pipeline import FILES

ALL_OFFICE, WARD_BY_WARD = FILES
NIGHT_START = int(datetime.fromisoformat("2026-10-26T19:50:00-04:00").timestamp() * 1000)
MINUTE_MS = 60_000
REPEAT_MINUTES = 10  # the Sept 28 repeat, 19:50 to 20:00
# When each file is generated within its night minute (ms): the test files' own offsets.
SEQ_OFFSET = {ALL_OFFICE: 1_807, WARD_BY_WARD: 1_787}
# Share of Reporting Units in by minutes after 20:00, 2023's night (research 01): 84% by 20:26,
# 97% by 21:24, the last `seq` at 23:37. Linear in between.
CURVE_MINUTES = (0, 26, 84, 217)
CURVE_SHARE = (0.0, 0.84, 0.97, 1.0)
COMPLETE_MINUTE = REPEAT_MINUTES + CURVE_MINUTES[-1]  # generation stops: 23:37
TIMEOUT_DELAY = 25.0  # seconds; past the pipeline's 20 s HTTP timeout
CACHE_CONTROL = "must-revalidate, max-age=0, s-maxage=0"  # the City's


@dataclass(frozen=True)
class Fault:
    kind: str
    files: tuple[str, ...]
    start: int  # night minutes after 19:50
    minutes: int
    race: str | None = None  # a per-race data fault's race id


# The fault script's HTTP faults (#17 § Rehearsal plan), 20 night minutes or more each: about two
# pipeline ticks at 10x.
FAULTS = (
    Fault("stall", FILES, 30, 30),  # 20:20-20:50: a long 304 run
    Fault("5xx", FILES, 70, 20),  # 21:00-21:20
    Fault("throttle", FILES, 100, 20),  # 21:30-21:50: a 403
    Fault("timeout", FILES, 130, 20),  # 22:00-22:20
    Fault("truncated", (ALL_OFFICE,), 160, 20),  # 22:30-22:50
    Fault("renamed", (WARD_BY_WARD,), 190, 20),  # 23:00-23:20
    Fault("one-file", (WARD_BY_WARD,), 220, 20),  # 23:30-23:50: a 503, all-office fine
)
HTTP_KINDS = {f.kind for f in FAULTS}

# The Full-night fault script (#48): every fault in #17's script, with clean minutes between the
# file-level ones. The per-race faults run together, one race each.
PER_RACE = 20  # 20:10-20:25
FULL_NIGHT = (
    Fault("row-unreadable", (ALL_OFFICE,), PER_RACE, 15, "councillor-4"),
    Fault("race-missing", (ALL_OFFICE,), PER_RACE, 15, "tcdsb-3"),
    Fault("received-above-polls", (ALL_OFFICE,), PER_RACE, 15, "councillor-6"),
    Fault("polls-zero", (ALL_OFFICE,), PER_RACE, 15, "tdsb-5"),
    Fault("polls-differ", (ALL_OFFICE,), PER_RACE, 15, "councillor-7"),
    Fault("votes-mismatch", (ALL_OFFICE,), PER_RACE, 15, "councillor-8"),
    Fault("above-expected", (ALL_OFFICE,), PER_RACE, 15, "councillor-10"),
    Fault("unknown-name", (ALL_OFFICE,), PER_RACE, 15, "councillor-12"),
    Fault("race-not-in-bundle", (ALL_OFFICE,), PER_RACE, 15, "councillor-26"),
    Fault("ward-votes-counted", (WARD_BY_WARD,), PER_RACE, 15, "mayor"),
    Fault("count-decrease", (ALL_OFFICE,), PER_RACE, 15, "councillor-14"),
    Fault("zeros", FILES, 40, 10),  # 20:30-20:40
    Fault("stall", FILES, 55, 30),  # 20:45-21:15: a long 304 run
    Fault("stalled-seq", FILES, 90, 10),  # 21:20-21:30: new counts, the seq frozen
    Fault("5xx", FILES, 105, 10),  # 21:35-21:45
    Fault("throttle", FILES, 120, 10),  # 21:50-22:00
    Fault("timeout", FILES, 135, 10),  # 22:05-22:15
    Fault("truncated", (ALL_OFFICE,), 150, 10),  # 22:20-22:30
    Fault("renamed", (WARD_BY_WARD,), 165, 10),  # 22:35-22:45
    Fault("one-file", (WARD_BY_WARD,), 180, 10),  # 22:50-23:00
    # 23:37-01:37: the council race of the last unit's ward shows 100% through the tail.
    Fault("all-in", (ALL_OFFICE,), COMPLETE_MINUTE, 120),
)
# The tail's arrivals, one unit each: 00:07, 00:37, 01:07 and 01:37.
FULL_NIGHT_TAIL = (257, 287, 317, 347)
UNKNOWN_NAME = "Rehearsal Unknown"
MAYOR_FAULT_WARD = "5"
DECREASE_MINUTES = 10  # a count decrease serves the race's count from this long before
UNAVAILABLE = (503, b"<html><body><h1>503 Service Unavailable</h1></body></html>\n")
ERRORS = {
    "5xx": UNAVAILABLE,
    "one-file": UNAVAILABLE,
    "throttle": (
        403,
        (
            b"<html><body><h1>403 ERROR</h1><p>The request could not be satisfied. "
            b"Request blocked.</p></body></html>\n"
        ),
    ),
}


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes
    delay: float = 0.0  # seconds to hold the response before sending it


@dataclass(frozen=True)
class _File:
    body: bytes
    etag: str
    last_modified: str


def _etag(body: bytes) -> str:
    return f'"{hashlib.md5(body).hexdigest()}"'


def _seq_of(file: _File) -> int:
    return int(json.loads(file.body)["seq"])


def _file(body: bytes) -> _File:
    seq = int(json.loads(body)["seq"])
    return _File(body, _etag(body), formatdate(seq / 1000, usegmt=True))


def _stamped(raw: bytes | dict, seq: int | None) -> bytes:
    """`raw` marked REHEARSAL, with `seq` if given."""
    data = json.loads(raw) if isinstance(raw, bytes) else raw
    data["electionDesc"] = f"{data.get('electionDesc') or ''} REHEARSAL".strip()
    if seq is not None:
        data["seq"] = str(seq)
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


def _row(data: dict, rid: str) -> tuple[list, int, dict]:
    """The all-office row of race `rid`: its office's row list, its index and the row."""
    for office in data["office"]:
        for i, row in enumerate(office["ward"]):
            if race_id(office["id"], row["num"]) == rid:
                return office["ward"], i, row
    raise KeyError(rid)


def _served_votes(candidates: list) -> dict[str, int] | None:
    try:
        return {c["name"]: int(c["votesReceived"]) for c in candidates}
    except KeyError, TypeError, ValueError:
        return None


def served_tallies(all_office: bytes, ward_by_ward: bytes) -> dict[str, dict[str, int] | None]:
    """Each race's candidate votes exactly as served: the exact-tallies reference.

    Read with plain `json` and `int`, not the pipeline's reader. The mayor's come from the
    ward-by-ward file, as the mayor card's do. A race whose votes can't be read is None.
    """
    tallies = {}
    for office in json.loads(all_office)["office"]:
        if office["id"] != MAYOR_OFFICE_ID:
            for row in office["ward"]:
                tallies[race_id(office["id"], row["num"])] = _served_votes(row["candidate"])
    candidates = json.loads(ward_by_ward)["office"]["candidate"]
    tallies[race_id(MAYOR_OFFICE_ID, "0")] = _served_votes(candidates)
    return tallies


class MockFeed:
    def __init__(
        self,
        scenario: Scenario,
        start_ms: int,
        speed: float,
        faults: tuple[Fault, ...] = FAULTS,
        tail: tuple[int, ...] = (),
    ):
        if speed <= 0:
            raise ValueError("speed must be positive")
        if any(t <= COMPLETE_MINUTE for t in tail) or list(tail) != sorted(set(tail)):
            raise ValueError("tail arrivals must be increasing and after the main count")
        self.scenario = scenario
        self.start_ms = start_ms
        self.speed = speed
        self.faults = faults
        self.tail = tail
        # The "all-in" fault's race: the council race in the ward of the last unit to arrive.
        last = scenario.night.units[scenario.order[-1]]
        self.all_in_race = race_id(COUNCILLOR_OFFICE_ID, str(last.ward))
        self._zeroed = {
            ALL_OFFICE: _file(_stamped(scenario.all_office, None)),
            WARD_BY_WARD: _file(_stamped(scenario.ward_by_ward, None)),
        }
        self._generation_files = lru_cache(maxsize=8)(self._files)

    def night_ms(self, now_ms: float) -> int:
        return NIGHT_START + int((now_ms - self.start_ms) * self.speed)

    def _fault(self, night_ms: int) -> Fault | None:
        """The HTTP fault at `night_ms`, if any."""
        minute = (night_ms - NIGHT_START) / MINUTE_MS
        return next(
            (
                f
                for f in self.faults
                if f.kind in HTTP_KINDS and f.start <= minute < f.start + f.minutes
            ),
            None,
        )

    def _data_faults(self, g: int) -> list[Fault]:
        """The data faults in generation `g`'s files."""
        return [
            f
            for f in self.faults
            if f.kind not in HTTP_KINDS and f.start <= g < f.start + f.minutes
        ]

    @property
    def last_generation(self) -> int:
        return self.tail[-1] if self.tail else COMPLETE_MINUTE

    def generation(self, now_ms: float) -> int | None:
        """The night minute (after 19:50) whose generation is served; None before the start."""
        if now_ms < self.start_ms:
            return None
        night_ms = self.night_ms(now_ms)
        fault = self._fault(night_ms)
        minute = (night_ms - NIGHT_START) // MINUTE_MS
        if fault and fault.kind == "stall":
            minute = fault.start
        if minute > COMPLETE_MINUTE:  # past the main count, only the tail's arrivals regenerate
            minute = max(g for g in (COMPLETE_MINUTE, *self.tail) if g <= minute)
        return minute

    def step_at(self, now_ms: float) -> int:
        """The true count's step the files hold at `now_ms`: the exact-tallies reference."""
        g = self.generation(now_ms)
        return 0 if g is None else self._step(g)

    def _step(self, g: int) -> int:
        # The main count holds back the tail's units, which then arrive one per tail minute.
        main = self.scenario.steps - len(self.tail)
        if g > COMPLETE_MINUTE:
            return main + sum(t <= g for t in self.tail)
        # The Sept 28 repeat runs the first minutes' count early, then the count restarts at 20:00.
        minutes = g if g < REPEAT_MINUTES else g - REPEAT_MINUTES
        share = float(np.interp(minutes, CURVE_MINUTES, CURVE_SHARE))
        return int(main * share)

    def _seq(self, file: str, g: int) -> int:
        """Generation `g`'s `seq` for `file`: its own minute's, unless a stalled `seq` holds it."""
        stalled = [f.start for f in self._data_faults(g) if f.kind == "stalled-seq"]
        return NIGHT_START + (stalled[0] if stalled else g) * MINUTE_MS + SEQ_OFFSET[file]

    def _files(self, g: int) -> dict[str, _File]:
        a, w = (json.loads(b) for b in self.scenario.count_snapshot(self._step(g)))
        for fault in self._data_faults(g):
            if fault.kind == "zeros":
                a, w = json.loads(self.scenario.all_office), json.loads(self.scenario.ward_by_ward)
            elif fault.kind != "stalled-seq":
                self._race_fault(fault, g, a, w)
        data = {ALL_OFFICE: a, WARD_BY_WARD: w}
        return {f: _file(_stamped(data[f], self._seq(f, g))) for f in FILES}

    def _race_fault(self, fault: Fault, g: int, a: dict, w: dict) -> None:
        """Apply a per-race data fault to generation `g`'s parsed files, in place."""
        kind = fault.kind
        if kind == "ward-votes-counted":  # in every candidate's repeat, so the repeats agree
            for candidate in w["office"]["candidate"]:
                for row in candidate["ward"]:
                    if row["num"] == MAYOR_FAULT_WARD:
                        row["votesCounted"] = str(int(row["votesCounted"]) + 1)
            return
        if kind == "race-not-in-bundle":  # a copy of the last council row, renumbered
            rows, _, last = _row(a, race_id(COUNCILLOR_OFFICE_ID, "25"))
            extra = copy.deepcopy(last)
            extra["num"], extra["name"] = fault.race.rsplit("-", 1)[1], "Rehearsal Ward"
            rows.append(extra)
            return
        rows, i, row = _row(a, self.all_in_race if kind == "all-in" else fault.race)
        if kind == "row-unreadable":
            row["candidate"][0]["votesReceived"] = "-"
        elif kind == "race-missing":
            rows.pop(i)
        elif kind == "received-above-polls":
            row["pollsReceived"] = str(int(row["polls"]) + 1)
        elif kind == "polls-zero":
            row["polls"] = "0"
        elif kind == "polls-differ":
            row["polls"] = str(int(row["polls"]) + 1)
        elif kind == "votes-mismatch":
            row["votesReceived"] = str(int(row["votesReceived"]) + 1)
        elif kind == "above-expected":  # more votes than electors: above any turnout grid
            top = row["candidate"][0]
            top["votesReceived"] = str(int(top["votesReceived"]) + 2 * int(row["totalVoters"]))
            row["votesReceived"] = str(sum(int(c["votesReceived"]) for c in row["candidate"]))
        elif kind == "unknown-name":
            row["candidate"][-1]["name"] = UNKNOWN_NAME
        elif kind == "count-decrease":
            earlier = self.scenario.true_count(self._step(max(g - DECREASE_MINUTES, 0)))
            fill_row(row, earlier.races[fault.race])
        elif kind == "all-in":
            row["pollsReceived"] = row["polls"]
        else:
            raise ValueError(f"unknown fault {kind!r}")

    def reference(self, a_seq: int, w_seq: int) -> list[dict[str, dict[str, int] | None]]:
        """The exact-tallies reference for a `seq` pair: `served_tallies` of each pair of files
        served under it, faults included. There is more than one only while a `seq` is stalled."""
        served = []
        if (_seq_of(self._zeroed[ALL_OFFICE]), _seq_of(self._zeroed[WARD_BY_WARD])) == (
            a_seq,
            w_seq,
        ):
            served.append(self._zeroed)
        for g in (*range(COMPLETE_MINUTE + 1), *self.tail):
            if (self._seq(ALL_OFFICE, g), self._seq(WARD_BY_WARD, g)) == (a_seq, w_seq):
                served.append(self._generation_files(g))
        return [served_tallies(f[ALL_OFFICE].body, f[WARD_BY_WARD].body) for f in served]

    def respond(self, file: str, now_ms: float, if_none_match: str | None) -> Response:
        """The response to a GET of `file` at wall-clock `now_ms`."""
        if file not in FILES:
            return Response(404, {"Content-Type": "text/plain"}, b"not found\n")
        g = self.generation(now_ms)
        current = self._zeroed[file] if g is None else self._generation_files(g)[file]
        fault = self._fault(self.night_ms(now_ms)) if g is not None else None
        kind = fault.kind if fault and file in fault.files else None
        if kind in ERRORS:
            status, body = ERRORS[kind]
            return Response(status, {"Content-Type": "text/html"}, body)
        if kind in ("truncated", "renamed"):
            if kind == "truncated":
                body = current.body[: len(current.body) // 2]
            else:  # only the ward-by-ward file's office is an object
                data = json.loads(current.body)
                data["office"]["candidates"] = data["office"].pop("candidate")
                body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            current = _File(body, _etag(body), current.last_modified)
        delay = TIMEOUT_DELAY if kind == "timeout" else 0.0
        headers = {
            "Cache-Control": CACHE_CONTROL,
            "ETag": current.etag,
            "Last-Modified": current.last_modified,
        }
        if if_none_match == current.etag:
            return Response(304, headers, b"", delay)
        return Response(200, {"Content-Type": "application/json", **headers}, current.body, delay)


# The `mock-feed` command's fault scripts: (faults, tail) by MOCK_FEED_FAULTS.
SCRIPTS = {
    "on": (FAULTS, ()),
    "full-night": (FULL_NIGHT, FULL_NIGHT_TAIL),
    "off": ((), ()),
}
