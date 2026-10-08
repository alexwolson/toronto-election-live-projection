"""The pipeline: every 60 s, read the City's two files and publish the payload to the store.

Each tick sends a conditional GET for both files over IPv4. Both must be readable (a 200 that
passes the snapshot checks, or a 304) or the pair is rejected, so a good file is never paired with
an older copy of the other. A readable pair is built into the payload, written through the store's
newest-pair script, and refreshes this pipeline's heartbeat whether or not the store took it.
"""

import http.client
import json
import math
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable

import redis

from election_night.feed import UnreadableFile, check_status
from election_night.payload import build_payload
from election_night.store import Store

FILES = ("unofficialresult.json", "unofficialresult-wardbyward.json")
PERIOD = 60  # seconds between ticks; the City publishes about every 60 s
STALL = 180  # the watchdog exits if no tick completes in this many seconds
HTTP_TIMEOUT = 20


def _ipv4_create_connection(address, *args, **kwargs):
    """socket.create_connection over the host's IPv4 addresses only, trying each in turn."""
    host, port = address
    error = OSError(f"no IPv4 address for {host}")
    for *_, (ip, _) in socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM):
        try:
            return socket.create_connection((ip, port), *args, **kwargs)
        except OSError as e:
            error = e
    raise error


class _IPv4HTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _ipv4_create_connection


class _IPv4HTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _ipv4_create_connection


class _IPv4HTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_IPv4HTTPConnection, req)


class _IPv4HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_IPv4HTTPSConnection, req, context=self._context)


_opener = urllib.request.build_opener(_IPv4HTTPHandler, _IPv4HTTPSHandler)


def http_get(url: str, etag: str | None) -> tuple[int, bytes, str | None]:
    """One conditional GET over IPv4: (status, body, ETag)."""
    request = urllib.request.Request(url, headers={"Accept-Encoding": "identity"})
    if etag:
        request.add_header("If-None-Match", etag)
    try:
        with _opener.open(request, timeout=HTTP_TIMEOUT) as response:
            return response.status, response.read(), response.headers.get("ETag")
    except urllib.error.HTTPError as error:
        return error.code, b"", None


def now_ms() -> int:
    return time.time_ns() // 1_000_000


class Pipeline:
    def __init__(
        self,
        name: str,
        base_url: str,
        bundle: dict,
        store: Store,
        get: Callable[[str, str | None], tuple[int, bytes, str | None]] = http_get,
        now_ms: Callable[[], int] = now_ms,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.bundle = bundle
        self.store = store
        self.get = get
        self.now_ms = now_ms
        self._cache: dict[str, tuple[bytes, str | None]] = {}  # file -> (body, ETag)

    def tick(self) -> dict:
        """Read both files once and publish; returns a log record of what happened."""
        record: dict = {"pipeline": self.name, "status": {}}
        pair = {}
        try:
            for name in FILES:
                cached = self._cache.get(name)
                status, body, etag = self.get(f"{self.base_url}/{name}", cached and cached[1])
                record["status"][name] = status
                check_status(status)
                if status == 304:
                    if cached is None:
                        raise UnreadableFile("304 without a cached copy")
                    pair[name] = cached
                else:
                    pair[name] = (body, etag)
            payload = build_payload(pair[FILES[0]][0], pair[FILES[1]][0], self.bundle)
        except UnreadableFile as error:
            record["rejected"] = str(error)
            return record
        self._cache.update(pair)
        record["read_ms"] = read_ms = self.now_ms()  # both files now held, valid and current
        record["seq"] = json.loads(payload)["seq"]
        record["stored"] = self.store.publish(payload)
        self.store.heartbeat(self.name, read_ms)
        return record


class Watchdog:
    """Exits the process if no tick completes within STALL seconds; the platform restarts it."""

    def __init__(
        self,
        stall: float = STALL,
        clock: Callable[[], float] = time.monotonic,
        exit: Callable[[int], object] = os._exit,
    ):
        self.stall = stall
        self.clock = clock
        self.exit = exit
        self.last = clock()

    def completed(self) -> None:
        self.last = self.clock()

    def check(self) -> None:
        if self.clock() - self.last > self.stall:
            self.exit(1)


def next_slot(now: float, stagger: float, last: float | None = None) -> float:
    """The next tick start: on the minute plus `stagger`, at or after `now`, and at least
    PERIOD seconds after the `last` start. A tick that overruns skips its next slot."""
    earliest = now if last is None else max(now, last + PERIOD)
    return math.ceil((earliest - stagger) / PERIOD) * PERIOD + stagger


def run(pipeline: Pipeline, stagger: float, watchdog: Watchdog) -> None:
    """Tick forever on the pipeline's own clock, one log line per tick on stderr."""

    def watch() -> None:
        while True:
            watchdog.check()
            time.sleep(5)

    threading.Thread(target=watch, daemon=True).start()
    last = None
    while True:
        start = next_slot(time.time(), stagger, last)
        time.sleep(max(0.0, start - time.time()))
        last = start
        try:
            record = pipeline.tick()
        except (OSError, http.client.HTTPException, redis.RedisError, ValueError) as error:
            # A failed read or write still completes the tick; the next slot retries.
            record = {"pipeline": pipeline.name, "error": repr(error)}
        watchdog.completed()
        print(json.dumps(record), file=sys.stderr, flush=True)
