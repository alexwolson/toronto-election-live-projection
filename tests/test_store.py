"""The store's newest-pair script, run as its exact Lua text against a local redis-server (S7)."""

import json

import pytest

from election_night.store import Store


def payload(a: int, w: int) -> bytes:
    return json.dumps({"seq": {"all_office": a, "ward_by_ward": w}, "n": f"{a}-{w}"}).encode()


@pytest.fixture
def store(redis_client):
    redis_client.flushdb()
    return Store(redis_client)


def test_an_empty_store_accepts_any_pair(store, redis_client):
    assert store.publish(payload(100, 200))
    assert redis_client.get("payload") == payload(100, 200)


@pytest.mark.parametrize(
    ("a", "w"),
    [(101, 200), (100, 201), (101, 201)],
    ids=["all-office-newer", "ward-by-ward-newer", "both-newer"],
)
def test_a_newer_pair_replaces_the_stored_one(store, redis_client, a, w):
    store.publish(payload(100, 200))
    assert store.publish(payload(a, w))
    assert redis_client.get("payload") == payload(a, w)


@pytest.mark.parametrize(
    ("a", "w"),
    [(100, 200), (99, 200), (100, 199), (99, 199), (101, 199), (99, 201)],
    ids=["equal", "all-office-older", "ward-by-ward-older", "both-older", "mixed", "mixed-other"],
)
def test_equal_older_and_mixed_pairs_are_rejected(store, redis_client, a, w):
    store.publish(payload(100, 200))
    assert not store.publish(payload(a, w))
    assert redis_client.get("payload") == payload(100, 200)


def test_seqs_compare_exactly_at_millisecond_scale(store):
    # 2026-10-26 20:01:00 EDT and one millisecond later.
    store.publish(payload(1793059260000, 1793059260000))
    assert store.publish(payload(1793059260001, 1793059260000))
    assert not store.publish(payload(1793059260000, 1793059260001))
