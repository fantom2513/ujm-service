from app.infrastructure.cache.redis_client import build_redis_client, prefixed_key


def test_build_redis_client_does_not_connect_eagerly():
    client = build_redis_client("redis://localhost:1/2")
    assert client is not None


def test_prefixed_key_adds_configured_prefix():
    assert prefixed_key("uxarch:", "sess:abc123") == "uxarch:sess:abc123"


def test_prefixed_key_does_not_double_prefix():
    assert prefixed_key("uxarch:", "uxarch:sess:abc123") == "uxarch:sess:abc123"
