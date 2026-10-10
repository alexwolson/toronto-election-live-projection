"""The switches (#49): store flags the Frontend route applies, flipped from the phone."""

import pytest

from election_night.switches import SWITCHES, flip, switch_key, switch_state


def test_the_six_switches_and_their_keys():
    assert SWITCHES == ("mayor", "council", "trustee", "mayor_variant", "projections", "page")
    assert switch_key("mayor_variant") == "switch:mayor_variant"


@pytest.mark.parametrize(
    ("raw", "state"),
    [
        (None, "on"),
        (b"on", "on"),
        (b"off", "off"),
        (b"of", "off (unrecognized value 'of')"),
        (b"", "off (unrecognized value '')"),
    ],
)
def test_a_missing_key_is_on_and_anything_but_on_fails_closed(raw, state):
    assert switch_state(raw) == state


def test_flip_writes_and_reads_back_each_way(redis_client):
    redis_client.flushdb()
    for name in SWITCHES:
        assert flip(redis_client, name, "off") == "off"
        assert redis_client.get(switch_key(name)) == b"off"
        assert flip(redis_client, name, "on") == "on"
        assert redis_client.get(switch_key(name)) == b"on"


def test_flip_refuses_an_unknown_switch_or_value(redis_client):
    with pytest.raises(ValueError):
        flip(redis_client, "ward-4", "off")
    with pytest.raises(ValueError):
        flip(redis_client, "page", "paused")
