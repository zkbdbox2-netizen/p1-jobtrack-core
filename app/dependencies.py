from collections.abc import AsyncGenerator

from redis.asyncio import Redis

from app.config import settings

# Module-level Redis client — created once, shared across all requests.
# Redis connections are multiplexed, so one client handles many concurrent requests.
_redis_client: Redis | None = None


async def get_redis() -> AsyncGenerator[Redis, None]:
    """
    FastAPI dependency that provides a Redis client.

    Usage in a route:
        async def my_route(redis: Redis = Depends(get_redis)):
            await redis.set("key", "value")
    """
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,   # return str instead of bytes — much easier to work with
        )
    yield _redis_client
