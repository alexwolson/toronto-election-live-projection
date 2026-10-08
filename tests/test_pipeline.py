"""The pipeline shell: heartbeats, archive, alerts, the 60 s slot clock and the watchdog."""

import json
import time
from itertools import pairwise
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from election_night.alerts import Alerts
from election_night.archive import Archive, ArchiveWriter
from election_night.bundle import OPENING_2026, build_bundle
from election_night.pipeline import Pipeline, Watchdog, next_slot
from election_night.store import Store

CITY = Path(__file__).parent / "fixtures" / "feed" / "city-2026"
BASE = "https://feed.test/results"
AO, WB = "unofficialresult.json", "unofficialresult-wardbyward.json"
WAYBACK = Path(__file__).parent / "fixtures" / "feed" / "wayback"
READER = "https://site.test/live/results.json"
ALERTS = Alerts(
    pipeline="https://hc.test/pipeline-fly",
    reader_path="https://hc.test/reader-path",
    count_decrease="https://hc.test/count-decrease",
    reader_path_url=READER,
)


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
        self.reader = (200, b"", None, None)  # the public /live/results.json

    def get(self, url: str, etag: str | None):
        if url == READER:
            if isinstance(self.reader, Exception):
                raise self.reader
            return self.reader
        name = url.removeprefix(BASE + "/")
        self.requests.append((name, etag))
        body = self.files[name]
        current = f'"{hash(body)}"'
        if self.status[name] is not None:
            return self.status[name], b"", None, None
        if etag == current:
            return 304, b"", current, None
        return 200, body, current, "Mon, 26 Oct 2026 20:01:00 GMT"


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
    assert redis_client.get("heartbeat:fly") == b"3000"  # after each file's receive time


def test_a_304_pair_refreshes_the_heartbeat(pipeline, feed, redis_client):
    pipeline.tick()
    pipeline.tick()
    assert [etag is not None for _, etag in feed.requests[2:]] == [True, True]
    assert redis_client.get("heartbeat:fly") == b"6000"


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
    assert redis_client.get("heartbeat:fly") == b"3000"
    assert redis_client.get("payload") == stored


def test_a_pair_the_store_rejects_still_refreshes_the_heartbeat(pipeline, store, redis_client):
    # The other pipeline already stored a newer pair; this read is valid, just not newer.
    store.publish(json.dumps({"seq": {"all_office": 9e15, "ward_by_ward": 9e15}}).encode())
    pipeline.tick()
    assert redis_client.get("heartbeat:fly") == b"3000"


class Pings(list):
    def __call__(self, url: str) -> None:
        self.append(url)


class FakeS3:
    def __init__(self):
        self.objects = {}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")

    def put_object(self, Bucket, Key, Body, Metadata):
        self.objects[Key] = (Body, Metadata)


class BrokenArchive:
    """An object store that hangs on one write and fails every other."""

    def __init__(self):
        self.calls = 0

    def put(self, key, body, metadata=None):
        self.calls += 1
        if self.calls == 1:
            time.sleep(5)
        raise OSError("store down")


def make_pipeline(feed, store, **kwargs):
    bundle = build_bundle((CITY / AO).read_bytes(), (CITY / WB).read_bytes(), OPENING_2026)
    clock = iter(range(1_000, 1_000_000, 1_000))
    return Pipeline("fly", BASE, bundle, store, get=feed.get, now_ms=lambda: next(clock), **kwargs)


def test_every_file_generation_and_payload_is_archived(feed, store, redis_client):
    s3 = FakeS3()
    writer = ArchiveWriter(Archive(s3, "night"))
    pipeline = make_pipeline(feed, store, archive=writer)
    pipeline.tick()
    pipeline.tick()  # two 304s: nothing new to archive
    writer.join()
    files = sorted(k for k in s3.objects if k.startswith("files/"))
    assert [k.split("/")[1] for k in files] == [WB, AO]
    body, metadata = s3.objects[next(k for k in files if f"/{AO}/" in k)]
    assert body == feed.files[AO]
    assert metadata == {
        "status": "200",
        "etag": f'"{hash(feed.files[AO])}"',
        "last-modified": "Mon, 26 Oct 2026 20:01:00 GMT",
        "received-ms": "1000",
    }
    (payload,) = [k for k in s3.objects if k.startswith("payloads/")]
    assert s3.objects[payload][0] == redis_client.get("payload")


def test_a_failing_archive_never_blocks_a_publish(feed, store, redis_client):
    pipeline = make_pipeline(feed, store, archive=ArchiveWriter(BrokenArchive()))
    start = time.monotonic()
    record = pipeline.tick()
    pipeline.complete(record)
    assert time.monotonic() - start < 1
    assert record["stored"] is True
    assert redis_client.get("payload") is not None


def test_each_completed_tick_pings_the_pipeline_check_even_when_the_pair_is_rejected(feed, store):
    pings = Pings()
    pipeline = make_pipeline(feed, store, alerts=ALERTS, ping=pings)
    feed.status[WB] = 500
    pipeline.complete(pipeline.tick())
    assert ALERTS.pipeline in pings


@pytest.mark.parametrize(
    ("reader", "pinged"),
    [
        ((200, b'{"heartbeat": 1000, "payload": {}}', None, None), True),
        ((200, b'{"heartbeat": -400000, "payload": {}}', None, None), False),
        ((500, b"", None, None), False),
        (OSError("unreachable"), False),
    ],
)
def test_the_probe_pings_reader_path_only_on_a_fresh_200(feed, store, reader, pinged):
    pings = Pings()
    feed.reader = reader
    pipeline = make_pipeline(feed, store, alerts=ALERTS, ping=pings)
    record = {"pipeline": "fly", "error": "a failed tick still probes"}
    pipeline.complete(record)
    assert (ALERTS.reader_path in pings) is pinged
    assert ALERTS.pipeline in pings
    assert record["reader_path"] is pinged


def counting_2023(feed):
    feed.files[AO] = (WAYBACK / "2023-20230627005628-all-office.json").read_bytes()
    feed.files[WB] = (WAYBACK / "2023-20230627002639-wardbyward.json").read_bytes()
    zero = (WAYBACK / "2023-20230627000639-all-office.json").read_bytes()
    return build_bundle(zero, feed.files[WB], opening_time="2023-06-26T20:00:00-04:00")


def edited(body: bytes, edit) -> bytes:
    data = json.loads(body)
    edit(data)
    data["seq"] = str(int(data["seq"]) + 1)
    return json.dumps(data).encode()


def test_a_citywide_mayoral_decrease_signals_and_is_recorded(feed, store, redis_client):
    pings = Pings()
    pipeline = make_pipeline(feed, store, alerts=ALERTS, ping=pings)
    pipeline.bundle = counting_2023(feed)
    pipeline.tick()

    def fewer(data):  # the mayor race is read from the ward-by-ward file
        candidate = data["office"]["candidate"][0]
        candidate["votesReceived"] = str(int(candidate["votesReceived"]) - 10)

    feed.files[WB] = edited(feed.files[WB], fewer)
    record = pipeline.tick()
    assert pings == [ALERTS.count_decrease + "/fail"]
    assert record["count_decreases"][0]["scope"] == "citywide"
    (stored,) = [json.loads(e) for e in redis_client.lrange("count_decreases", 0, -1)]
    assert stored["pipeline"] == "fly"
    assert stored["scope"] == "citywide"
    assert stored["after"] == stored["before"] - 10


def test_a_ward_level_decrease_is_recorded_but_silent(feed, store, redis_client):
    pings = Pings()
    pipeline = make_pipeline(feed, store, alerts=ALERTS, ping=pings)
    pipeline.bundle = counting_2023(feed)
    pipeline.tick()

    def fewer(data):
        for candidate in data["office"]["candidate"]:
            ward = candidate["ward"][0]
            ward["votesCounted"] = str(int(ward["votesCounted"]) - 1)

    feed.files[WB] = edited(feed.files[WB], fewer)
    pipeline.tick()
    assert pings == []
    (stored,) = [json.loads(e) for e in redis_client.lrange("count_decreases", 0, -1)]
    assert (stored["scope"], stored["race"], stored["ward"]) == ("ward", "mayor", "1")


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
