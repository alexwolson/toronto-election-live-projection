def test_redis_server_is_reachable(redis_client):
    assert redis_client.ping()
