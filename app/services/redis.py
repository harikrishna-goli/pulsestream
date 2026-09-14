from redis.asyncio import Redis, ConnectionPool
from app.config import settings

redis_pool = ConnectionPool.from_url(
                                        settings.REDIS_URL,
                                        decode_responses=True,
                                        socket_timeout=settings.REDIS_TIMEOUT_SECONDS,
                                        socket_connect_timeout=settings.REDIS_TIMEOUT_SECONDS,
                                        max_connections=50
                                        )

def get_redis_client() -> Redis:
    return Redis(connection_pool=redis_pool)