from redis.asyncio import Redis, from_url


def build_redis_client(redis_url: str) -> Redis:
    # from_url is lazy — no connection is opened until the first command,
    # matching Phase 0 scope: wiring only, no consumer until Phase 2/3.
    return from_url(redis_url, decode_responses=True)


def prefixed_key(prefix: str, key: str) -> str:
    if key.startswith(prefix):
        return key
    return f"{prefix}{key}"
