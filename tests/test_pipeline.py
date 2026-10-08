"""The pipeline shell: heartbeats, the 60 s slot clock and the watchdog."""

import json
from itertools import pairwise
from pathlib import Path

import pytest

from election_night.bundle import OPENING_2026, build_bundle
from election_night.pipeline import Pipeline, Watchdog, next_slot
from election_night.store import Store

CITY = Path(__file__).parent / "fixtures" / "feed" / "city-2026"
BASE = "https://feed.test/results"
AO, WB = "unofficialresult.json", "unofficialresult-wardbyward.json"


def restamped(body: bytes, seq: int) -> bytes:
    data = json.loads(body)
    data["seq"] = str(seq)
    return json.dumps(data).encode()


class FakeFeed:
    """The City's two files, answered per URL; records each request's If-None-Match."""

    def __init__(self):
        self.files = {AO: (CITY / AO).read_bytes(), WB: (CITY / WB).read_bytes()}
        self.status = {AO: None, WB: None}  # None answers 200, or 304 on a matching ETag
        self.requests = []

    def get(self, url: str, etag: str | None):
        name = url.removeprefix(BASE + "/")
        self.requests.append((name, etag))
        body = self.files[name]
        current = f'"{hash(body)}"'
        if self.status[name] is not None:
            return self.status[name], b"", None
        if etag == current:
            return 304, b"", current
        return 200, body, current


@pytest.fixture
def feed():
    return FakeFeed()


@pytest.fixture
def store(redis_client):
    redis_client.flushdb()
    return Store(redis_client)


@pytest.fixture
def pipeline(feed, store):
    bundle = build_bundle((CITY / AO).read_bytes(), (CITY / WB).read_bytes(), OPENING_2026)
    clock = iter(range(1_000, 1_000_000, 1_000))
    return Pipeline("fly", BASE, bundle, store, get=feed.get, now_ms=lambda: next(clock))


def test_a_valid_200_pair_stores_the_payload_and_a_heartbeat(pipeline, redis_client):
    pipeline.tick()
    assert json.loads(redis_client.get("payload"))["state"] == "before_results"
    assert redis_client.get("heartbeat:fly") == b"1000"


def test_a_304_pair_refreshes_the_heartbeat(pipeline, feed, redis_client):
    pipeline.tick()
    pipeline.tick()
    assert [etag is not None for _, etag in feed.requests[2:]] == [True, True]
    assert redis_client.get("heartbeat:fly") == b"2000"


def test_a_newer_200_with_a_304_pairs_the_new_file_with_the_current_copy(
    pipeline, feed, redis_client
):
    pipeline.tick()
    seq = json.loads(redis_client.get("payload"))["seq"]
    feed.files[AO] = restamped(feed.files[AO], seq["all_office"] + 1)
    pipeline.tick()
    assert json.loads(redis_client.get("payload"))["seq"] == {
        "all_office": seq["all_office"] + 1,
        "ward_by_ward": seq["ward_by_ward"],
    }


@pytest.mark.parametrize("fault", ["status-500", "not-json", "no-seq"])
def test_an_unreadable_file_rejects_the_pair_and_leaves_the_heartbeat(
    pipeline, feed, redis_client, fault
):
    pipeline.tick()
    stored = redis_client.get("payload")
    feed.files[AO] = restamped(feed.files[AO], 9_999_999_999_999)
    if fault == "status-500":
        feed.status[WB] = 500
    elif fault == "not-json":
        feed.files[WB] = b"<html>"
    else:
        feed.files[WB] = json.dumps({"office": {"candidate": []}}).encode()
    pipeline.tick()
    assert redis_client.get("heartbeat:fly") == b"1000"
    assert redis_client.get("payload") == stored


def test_a_pair_the_store_rejects_still_refreshes_the_heartbeat(pipeline, store, redis_client):
    # The other pipeline already stored a newer pair; this read is valid, just not newer.
    store.publish(json.dumps({"seq": {"all_office": 9e15, "ward_by_ward": 9e15}}).encode())
    pipeline.tick()
    assert redis_client.get("heartbeat:fly") == b"1000"


class Clock:
    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_the_watchdog_exits_when_no_tick_completes_in_3_minutes():
    clock, exits = Clock(), []
    watchdog = Watchdog(clock=clock, exit=exits.append)
    clock.t = 179
    watchdog.check()
    assert exits == []
    clock.t = 181
    watchdog.check()
    assert exits == [1]


def test_a_completed_tick_resets_the_watchdog():
    clock, exits = Clock(), []
    watchdog = Watchdog(clock=clock, exit=exits.append)
    clock.t = 170
    watchdog.completed()
    clock.t = 340
    watchdog.check()
    assert exits == []
    clock.t = 351
    watchdog.check()
    assert exits == [1]


def test_ticks_run_on_the_staggered_minute_and_never_faster_than_every_60_s():
    # Tick durations, including one that overruns its slot and one that ends exactly on one.
    durations = [2.0, 0.5, 75.0, 1.0, 58.0, 30.0]
    now, last, starts = 1_000_012.3, None, []
    for duration in durations:
        start = next_slot(now, stagger=30, last=last)
        assert start >= now
        starts.append(start)
        last, now = start, start + duration
    assert [s % 60 for s in starts] == [30] * len(durations)
    assert all(b - a >= 60 for a, b in pairwise(starts))
    assert starts[3] - starts[2] == 120  # the overrun skips a slot rather than ticking late
