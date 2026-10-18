"""`night status` (#50): a read-only summary of the store, for the job summary on the phone.

It prints both heartbeats, the stored `seq` pair, each switch and Night Close as the route reads
them (#49, #51), the current Withdrawals with their machine reasons, and the count decreases the pipelines recorded
(#17 § On the night). It reads with one MGET and one LRANGE and never writes. A malformed key
spoils only its own section or row. With `--fly-app`, it also lists each Fly app's Machines
(#111): a Machine on an unreachable host survives a deploy and comes back later on the old image.
"""

import json
import shutil
import subprocess
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from election_night.alerts import FRESH_MS as STALE_MS  # one rule (#17 § Staleness)
from election_night.night_close import KEY as NIGHT_CLOSE_KEY
from election_night.night_close import night_close_state
from election_night.store import (
    CHECK_NOTES_KEY,
    DECREASES_KEY,
    PAYLOAD_KEY,
    PIPELINES,
    SEQ_KEY,
    heartbeat_key,
)
from election_night.switches import SWITCHES, switch_key, switch_state

TORONTO = ZoneInfo("America/Toronto")
KEYS = (
    PAYLOAD_KEY,
    SEQ_KEY,
    *(heartbeat_key(p) for p in PIPELINES),
    *(switch_key(s) for s in SWITCHES),
    NIGHT_CLOSE_KEY,
)


def read_status(client) -> dict:
    """The store's raw values by key: one MGET, then the count decreases list and the check
    notes."""
    values = dict(zip(KEYS, client.mget(KEYS), strict=True))
    values[DECREASES_KEY] = client.lrange(DECREASES_KEY, 0, -1)
    values[CHECK_NOTES_KEY] = client.hgetall(CHECK_NOTES_KEY)
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


def _night_close(values: dict, now_ms: int) -> list[str]:
    state = night_close_state(values.get(NIGHT_CLOSE_KEY))
    if state == "closed":
        return ["**Closed.** The page shows the final unofficial count."]
    return [state[0].upper() + state[1:] + "."]


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


def _check_notes(values: dict, now_ms: int) -> list[str]:
    """Contained faults (#97): the projection carried on, each listed once, newest first."""
    entries = sorted(
        (json.loads(e) for e in values[CHECK_NOTES_KEY].values()),
        key=lambda e: e["ms"],
        reverse=True,
    )
    if not entries:
        return ["None."]
    rows = [[_clock(e["ms"]), e["pipeline"], e["race"], e["reason"]] for e in entries]
    return _table(["First seen", "Pipeline", "Race", "Reason"], rows)


SECTIONS = (
    ("Heartbeats", _heartbeats),
    ("Stored seq pair", _seq),
    ("Switches", _switches),
    ("Night Close", _night_close),
    ("Withdrawals", _withdrawals),
    ("Check notes", _check_notes),
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


def list_machines(apps: list[str]) -> dict[str, list | str]:
    """Each Fly app's Machines from `flyctl machine list --json` (#111), or why they couldn't be
    listed. Read-only."""
    if shutil.which("flyctl") is None:
        return {app: "flyctl is not installed" for app in apps}
    listed: dict[str, list | str] = {}
    for app in apps:
        try:
            done = subprocess.run(
                ["flyctl", "machine", "list", "-a", app, "--json"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except subprocess.TimeoutExpired:
            listed[app] = "flyctl timed out"
            continue
        if done.returncode != 0:
            listed[app] = " ".join(done.stderr.split()) or f"flyctl exited {done.returncode}"
            continue
        try:
            listed[app] = json.loads(done.stdout)
        except ValueError:
            listed[app] = "flyctl returned unreadable JSON"
    return listed


def _digest(m: dict) -> str:
    return (m.get("image_ref") or {}).get("digest") or "?"


def render_machines(apps: dict[str, list | str]) -> list[str]:
    """The Machines section (#111): each app should run exactly one started Machine. A Machine on
    an unreachable host survives a deploy and comes back later on the old image, beside the new one.
    """
    rows = []
    for app, machines in apps.items():
        if isinstance(machines, str):
            rows.append([app, "", "", "", "", f"**Couldn't check:** {machines}"])
            continue
        if not machines:
            rows.append([app, "", "", "", "", "**no Machines**"])
            continue
        count = "" if len(machines) == 1 else f"**{len(machines)} Machines, expected 1**"
        mixed = len({_digest(m) for m in machines}) > 1
        for m in machines:
            flags = [count] if count else []
            if m.get("state") != "started":
                flags.append("**not started**")
            if mixed:
                flags.append("**images differ**")
            digest = f"`{_digest(m)}`"
            state, region = m.get("state", "?"), m.get("region", "?")
            rows.append([app, m["id"], state, region, digest, ", ".join(flags)])
    return _table(["App", "Machine", "State", "Region", "Digest", ""], rows)
