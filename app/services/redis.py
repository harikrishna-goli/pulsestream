from redis.asyncio import Redis, ConnectionPool
from app.config import settings

# Upstash Redis uses rediss:// (TLS encrypted connections).
# By default, redis-py tries to verify the SSL certificate chain.
# Upstash uses certificates that redis-py sometimes cannot verify,
# causing "Connection closed by server" errors.
# Setting ssl_cert_reqs=None skips certificate verification.
# The connection is still fully encrypted — we just skip the cert check.
_pool_kwargs = dict(
    decode_responses=True,
    socket_timeout=settings.REDIS_TIMEOUT_SECONDS,
    socket_connect_timeout=settings.REDIS_TIMEOUT_SECONDS,
    max_connections=50,
)

if settings.REDIS_URL and settings.REDIS_URL.startswith("rediss://"):
    _pool_kwargs["ssl_cert_reqs"] = None

redis_pool = ConnectionPool.from_url(settings.REDIS_URL, **_pool_kwargs)

def get_redis_client() -> Redis:
    return Redis(connection_pool=redis_pool)