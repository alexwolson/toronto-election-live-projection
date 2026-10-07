import os

import pytest
import redis


@pytest.fixture
def redis_client():
    """A client for the local Redis server at REDIS_URL.

    Skipped when REDIS_URL is unset, except in CI, where it must be set.
    """
    url = os.environ.get("REDIS_URL")
    if not url:
        if os.environ.get("CI"):
            pytest.fail("REDIS_URL must be set in CI")
        pytest.skip("REDIS_URL is not set")
    client = redis.Redis.from_url(url)
    yield client
    client.close()
