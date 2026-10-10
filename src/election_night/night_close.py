"""Night Close (#51; #17 § Switches, heartbeats, staleness and Night Close): a store flag Alex
sets by hand once neither file has changed for 2 hours. The Frontend route passes it; the
pipelines never read it.

`night_close` holds `closed`; a missing key is open. Unlike the switches, any other value is
open, so a typo in the Upstash console never puts up "Elected (unofficial)", and `night status`
names it (docs/store.md).
"""

KEY = "night_close"
CLOSED = b"closed"


def night_close_state(raw: bytes | None) -> str:
    """How the route reads the flag's raw value."""
    if raw is None:
        return "open"
    if raw == CLOSED:
        return "closed"
    return f"open (unrecognized value {raw.decode(errors='replace')!r})"


def close(client) -> str:
    """Declare Night Close and return the flag read back from the store."""
    client.set(KEY, CLOSED)
    return night_close_state(client.get(KEY))


def clear(client) -> str:
    """Clear Night Close and return the flag read back from the store."""
    client.delete(KEY)
    return night_close_state(client.get(KEY))
