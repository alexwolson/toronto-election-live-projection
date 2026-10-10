"""`night status` (#50): a read-only summary of the store, for the job summary on the phone.

It prints both heartbeats, the stored `seq` pair, each switch as the route reads it (#49), the
current Withdrawals with their machine reasons, and the count decreases the pipelines recorded
(#17 § On the night). It reads with one MGET and one LRANGE and never writes. A malformed key
spoils only its own section or row.
"""

import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from election_night.alerts import FRESH_MS as STALE_MS  # one rule (#17 § Staleness)
from election_night.store import DECREASES_KEY, PAYLOAD_KEY, PIPELINES, SEQ_KEY, heartbeat_key
from election_night.switches import SWITCHES, switch_key, switch_state

TORONTO = ZoneInfo("America/Toronto")
KEYS = (
    PAYLOAD_KEY,
    SEQ_KEY,
    *(heartbeat_key(p) for p in PIPELINES),
    *(switch_key(s) for s in SWITCHES),
)


def read_status(client) -> dict:
    """The store's raw values by key: one MGET, then the count decreases list."""
    values = dict(zip(KEYS, client.mget(KEYS), strict=True))
    values[DECREASES_KEY] = client.lrange(DECREASES_KEY, 0, -1)
    return values


def _clock(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).astimezone(TORONTO).strftime("%H:%M:%S %Z")


def _age(ms: int, now_ms: int) -> str:
    seconds = max(0, (now_ms - ms) // 1000)
    if seconds < 60:
        return f"{seconds} s ago"
    hours, minutes = divmod(seconds // 60, 60)
    return f"{hours} h {minutes} min ago" if hours else f"{minutes} min ago"


UNREADABLE = "Unreadable in the store."
MALFORMED = (ValueError, TypeError, KeyError, AttributeError)


def _table(header: list[str], rows: list[list]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return lines + ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]


def _heartbeat_row(pipeline: str, raw: bytes | None, now_ms: int) -> list:
    if raw is None:
        return [pipeline, "never written", "", "stale"]
    try:
        ms = int(raw)
    except MALFORMED:
        return [pipeline, UNREADABLE, "", "stale"]
    stale = "stale" if now_ms - ms > STALE_MS else ""
    return [pipeline, _clock(ms), _age(ms, now_ms), stale]


def _heartbeats(values: dict, now_ms: int) -> list[str]:
    rows = [_heartbeat_row(p, values.get(heartbeat_key(p)), now_ms) for p in PIPELINES]
    return _table(["Pipeline", "Last valid read", "Age", ""], rows)


def _seq(values: dict, now_ms: int) -> list[str]:
    raw = values.get(SEQ_KEY)
    if raw is None:
        return ["None."]
    a, w = (int(s) for s in raw.decode().split(","))
    rows = [
        ["all-office", _clock(a), _age(a, now_ms)],
        ["ward-by-ward", _clock(w), _age(w, now_ms)],
    ]
    return _table(["File", "City time", "Age"], rows) + [
        "",
        f"City count as of {_clock(min(a, w))}.",
    ]


def _withdrawals(values: dict, now_ms: int) -> list[str]:
    if values.get(PAYLOAD_KEY) is None:
        return ["No payload in the store."]
    races = json.loads(values[PAYLOAD_KEY])["races"]
    rows = [[r["id"], r["withdrawal"]["reason"]] for r in races if r.get("withdrawal")]
    return _table(["Race", "Reason"], rows) if rows else ["None."]


def _switches(values: dict, now_ms: int) -> list[str]:
    rows = []
    for name in SWITCHES:
        raw = values.get(switch_key(name))
        state = switch_state(raw)
        if raw is None:
            state = "on (not set)"
        elif state != "on":
            state = f"**{state}**"
        rows.append([name, state])
    return _table(["Switch", "State"], rows)


def _decreases(values: dict, now_ms: int) -> list[str]:
    entries = sorted(
        (json.loads(e) for e in values[DECREASES_KEY]), key=lambda e: e["ms"], reverse=True
    )
    if not entries:
        return ["None."]
    rows = [
        [
            _clock(e["ms"]),
            e["pipeline"],
            f"**{e['scope']}**" if e["scope"] == "citywide" else e["scope"],
            e["race"],
            e.get("ward", ""),
            e["before"],
            e["after"],
        ]
        for e in entries
    ]
    return _table(["Seen", "Pipeline", "Scope", "Race", "Ward", "Before", "After"], rows)


SECTIONS = (
    ("Heartbeats", _heartbeats),
    ("Stored seq pair", _seq),
    ("Switches", _switches),
    ("Withdrawals", _withdrawals),
    ("Count decreases", _decreases),
)


def render_status(values: dict, now_ms: int) -> str:
    """The job summary's Markdown, from the store's raw values."""
    lines = [f"# Night status at {_clock(now_ms)}"]
    for title, section in SECTIONS:
        try:
            body = section(values, now_ms)
        except MALFORMED:
            body = [UNREADABLE]
        lines += ["", f"## {title}", ""] + body
    return "\n".join(lines) + "\n"
