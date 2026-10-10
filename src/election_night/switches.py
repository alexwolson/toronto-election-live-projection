"""The switches (#49; #17 § Switches): store flags the Frontend route applies, never the
pipelines. One per level, the mayor's variant, all projections, and a page pause.

`switch:<name>` holds `on` or `off`; a missing key is on. Any other value turns the switch off,
so a typo in the Upstash console fails closed, and `night status` names it (docs/store.md).
"""

SWITCHES = ("mayor", "council", "trustee", "mayor_variant", "projections", "page")
VALUES = ("on", "off")


def switch_key(name: str) -> str:
    return f"switch:{name}"


def switch_state(raw: bytes | None) -> str:
    """How the route reads a switch's raw value."""
    if raw is None or raw == b"on":
        return "on"
    if raw == b"off":
        return "off"
    return f"off (unrecognized value {raw.decode(errors='replace')!r})"


def flip(client, name: str, value: str) -> str:
    """Set one switch and return its state read back from the store."""
    if name not in SWITCHES or value not in VALUES:
        raise ValueError(f"no switch {name!r} with value {value!r}")
    client.set(switch_key(name), value)
    return switch_state(client.get(switch_key(name)))
