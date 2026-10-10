"""`night status`: a read-only summary of the store for the job summary (#50)."""

import json

import pytest

from election_night.status import read_status, render_status
from election_night.store import Store
from election_night.switches import SWITCHES

# 2026-10-26 20:10:00 EDT
NOW = 1793059800000
MIN = 60_000


def payload(withdrawals: dict[str, str] | None = None) -> bytes:
    races = [
        {"id": "mayor", "withdrawal": None},
        {"id": "councillor-4", "withdrawal": None},
        {"id": "tdsb-5", "withdrawal": None},
    ]
    for race in races:
        if withdrawals and race["id"] in withdrawals:
            race["withdrawal"] = {"reason": withdrawals[race["id"]]}
    return json.dumps(
        {"seq": {"all_office": NOW - 3 * MIN, "ward_by_ward": NOW - 2 * MIN}, "races": races}
    ).encode()


def stored(**overrides) -> dict:
    """The store's raw values, as read_status returns them."""
    values = {
        "payload": payload(),
        "payload:seq": f"{NOW - 3 * MIN},{NOW - 2 * MIN}".encode(),
        "heartbeat:fly": str(NOW - MIN).encode(),
        "heartbeat:do": str(NOW - 30_000).encode(),
        "count_decreases": [],
        **{f"switch:{name}": None for name in SWITCHES},
        "night_close": None,
    }
    values.update(overrides)
    return values


def test_heartbeats_show_time_and_age_and_flag_a_stale_one():
    text = render_status(stored(**{"heartbeat:do": str(NOW - 7 * MIN).encode()}), NOW)
    assert "| fly | 20:09:00 EDT | 1 min ago |  |" in text
    assert "| do | 20:03:00 EDT | 7 min ago | stale |" in text


def test_a_missing_heartbeat_says_so():
    text = render_status(stored(**{"heartbeat:fly": None}), NOW)
    assert "| fly | never written |  | stale |" in text


def test_the_seq_pair_and_city_count_as_of_the_older_seq():
    text = render_status(stored(), NOW)
    assert "| all-office | 20:07:00 EDT |" in text
    assert "| ward-by-ward | 20:08:00 EDT |" in text
    assert "City count as of 20:07:00 EDT" in text


def test_current_withdrawals_with_their_machine_reasons():
    text = render_status(stored(payload=payload({"councillor-4": "progress_regressed"})), NOW)
    assert "| councillor-4 | progress_regressed |" in text
    assert "mayor" not in text.split("## Withdrawals")[1].split("##")[0]


def test_no_withdrawals_and_no_decreases_say_none():
    text = render_status(stored(), NOW)
    assert "## Withdrawals\n\nNone." in text
    assert "## Count decreases\n\nNone." in text


def test_count_decreases_newest_first_with_citywide_marked():
    entries = [
        {
            "pipeline": "fly",
            "seq": {},
            "ms": NOW - 5 * MIN,
            "scope": "ward",
            "race": "mayor",
            "ward": "3",
            "before": 40,
            "after": 39,
        },
        {
            "pipeline": "do",
            "seq": {},
            "ms": NOW - MIN,
            "scope": "citywide",
            "race": "mayor",
            "before": 150,
            "after": 140,
        },
    ]
    text = render_status(stored(count_decreases=[json.dumps(e).encode() for e in entries]), NOW)
    section = text.split("## Count decreases")[1]
    assert section.index("citywide") < section.index("| ward |")
    assert "| 20:09:00 EDT | do | **citywide** | mayor |  | 150 | 140 |" in section
    assert "| 20:05:00 EDT | fly | ward | mayor | 3 | 40 | 39 |" in section


def test_an_empty_store_renders_without_failing():
    empty = {key: None for key in stored() if key != "count_decreases"}
    text = render_status({**empty, "count_decreases": []}, NOW)
    assert "No payload in the store." in text


class ReadOnlyClient:
    """Only the read commands night status may use; any write would raise AttributeError."""

    def __init__(self, values: dict):
        self.values = values

    def mget(self, keys):
        return [self.values.get(k) for k in keys]

    def lrange(self, key, start, end):
        return self.values.get(key, [])


def test_reading_the_store_uses_only_read_commands():
    values = stored()
    assert read_status(ReadOnlyClient(values)) == values


def test_read_status_reads_what_the_pipelines_write(redis_client):
    redis_client.flushdb()
    store = Store(redis_client)
    store.publish(payload())
    store.heartbeat("fly", NOW)
    store.record_decreases([{"scope": "area", "race": "tdsb-5", "before": 2, "after": 1}])
    values = read_status(redis_client)
    assert values["payload"] == payload()
    assert values["heartbeat:fly"] == str(NOW).encode()
    assert values["heartbeat:do"] is None
    assert [json.loads(e)["race"] for e in values["count_decreases"]] == ["tdsb-5"]


def test_an_unreadable_payload_is_reported_not_raised():
    text = render_status(stored(payload=b'{"seq": {}}'), NOW)
    assert "Unreadable in the store." in text
    assert "## Count decreases" in text


def test_a_malformed_key_spoils_only_its_own_section():
    text = render_status(
        stored(**{"heartbeat:do": b"soon", "count_decreases": [b"{not json"]}), NOW
    )
    assert "| fly | 20:09:00 EDT | 1 min ago |  |" in text
    assert "## Withdrawals\n\nNone." in text
    assert text.count("Unreadable in the store.") == 2


def test_switches_show_each_state_with_a_missing_key_on():
    text = render_status(
        stored(**{"switch:council": b"off", "switch:page": b"on", "switch:trustee": b"of"}), NOW
    )
    section = text.split("## Switches")[1].split("##")[0]
    assert "| mayor | on (not set) |" in section
    assert "| council | **off** |" in section
    assert "| trustee | **off (unrecognized value 'of')** |" in section
    assert "| page | on |" in section


def test_read_status_reads_the_switches(redis_client):
    redis_client.flushdb()
    redis_client.set("switch:projections", "off")
    values = read_status(redis_client)
    assert values["switch:projections"] == b"off"
    assert values["switch:page"] is None


@pytest.mark.parametrize(
    ("raw", "line"),
    [
        (None, "Open."),
        (b"closed", "**Closed.** The page shows the final unofficial count."),
        (b"Closed", "Open (unrecognized value 'Closed')."),
    ],
)
def test_night_close_shows_as_the_route_reads_it(raw, line):
    text = render_status(stored(night_close=raw), NOW)
    assert f"## Night Close\n\n{line}" in text


def test_read_status_reads_night_close(redis_client):
    redis_client.flushdb()
    redis_client.set("night_close", "closed")
    assert read_status(redis_client)["night_close"] == b"closed"
