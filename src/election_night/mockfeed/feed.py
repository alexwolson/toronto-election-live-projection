"""The Mock Feed's responses: the scenario served as the City serves its two files (#37).

Each response is a pure function of the scenario, start time, speed, clock and request. The start
maps to 19:50 EDT on Oct 26 and the night clock runs at `speed`. Each file is generated once a
night minute, the ward-by-ward file 20 ms before the all-office one (as in the City's test files),
until the count is complete; then its last `seq` stays frozen. Units arrive on 2023's observed
curve from 20:00. From 19:50 the first minutes repeat the Sept 28 incident: live-looking data,
then the files regenerated as zeros at 20:00. Every file says REHEARSAL in `electionDesc`.

The HTTP faults are scheduled on the night clock and never overlap; `faults=()` turns them off.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from email.utils import formatdate
from functools import lru_cache

import numpy as np

from election_night.mockfeed.scenario import Scenario
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


def _file(body: bytes) -> _File:
    seq = int(json.loads(body)["seq"])
    return _File(body, _etag(body), formatdate(seq / 1000, usegmt=True))


def _stamped(raw: bytes, seq: int | None) -> bytes:
    """`raw` marked REHEARSAL, with `seq` if given."""
    data = json.loads(raw)
    data["electionDesc"] = f"{data.get('electionDesc') or ''} REHEARSAL".strip()
    if seq is not None:
        data["seq"] = str(seq)
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


class MockFeed:
    def __init__(
        self, scenario: Scenario, start_ms: int, speed: float, faults: tuple[Fault, ...] = FAULTS
    ):
        if speed <= 0:
            raise ValueError("speed must be positive")
        self.scenario = scenario
        self.start_ms = start_ms
        self.speed = speed
        self.faults = faults
        self._zeroed = {
            ALL_OFFICE: _file(_stamped(scenario.all_office, None)),
            WARD_BY_WARD: _file(_stamped(scenario.ward_by_ward, None)),
        }
        self._generation_files = lru_cache(maxsize=8)(self._files)

    def night_ms(self, now_ms: float) -> int:
        return NIGHT_START + int((now_ms - self.start_ms) * self.speed)

    def _fault(self, night_ms: int) -> Fault | None:
        minute = (night_ms - NIGHT_START) / MINUTE_MS
        return next((f for f in self.faults if f.start <= minute < f.start + f.minutes), None)

    def generation(self, now_ms: float) -> int | None:
        """The night minute (after 19:50) whose generation is served; None before the start."""
        if now_ms < self.start_ms:
            return None
        night_ms = self.night_ms(now_ms)
        fault = self._fault(night_ms)
        if fault and fault.kind == "stall":
            return min(fault.start, COMPLETE_MINUTE)
        return min((night_ms - NIGHT_START) // MINUTE_MS, COMPLETE_MINUTE)

    def step_at(self, now_ms: float) -> int:
        """The true count's step the files hold at `now_ms`: the exact-tallies reference."""
        g = self.generation(now_ms)
        return 0 if g is None else self._step(g)

    def _step(self, g: int) -> int:
        # The Sept 28 repeat runs the first minutes' count early, then the count restarts at 20:00.
        minutes = g if g < REPEAT_MINUTES else g - REPEAT_MINUTES
        share = float(np.interp(minutes, CURVE_MINUTES, CURVE_SHARE))
        return int(self.scenario.steps * share)

    def _files(self, g: int) -> dict[str, _File]:
        bodies = dict(zip(FILES, self.scenario.count_snapshot(self._step(g))))
        seq = NIGHT_START + g * MINUTE_MS
        return {f: _file(_stamped(bodies[f], seq + SEQ_OFFSET[f])) for f in FILES}

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
