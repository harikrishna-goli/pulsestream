import time
from collections import defaultdict
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from app.config import settings
from app.services.redis import get_redis_client
from app.services.security import hash_key
import logging

logger = logging.getLogger(__name__)

TOKEN_BUCKET_LUA_SCRIPT = """
-- KEYS[1]: Rate limit key, e.g. "ratelimit:tenant_acme"
-- ARGV[1]: Capacity (e.g. 60)
-- ARGV[2]: Refill rate per second (e.g. 1.0)
-- ARGV[3]: Current timestamp in seconds (float)
-- ARGV[4]: Cost per request (default 1)

local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])

local data = redis.call("HMGET", key, "tokens", "last_updated")
local tokens = tonumber(data[1])
local last_updated = tonumber(data[2])

if not tokens then
    tokens = capacity
    last_updated = now
else
    local delta = math.max(0, now - last_updated)
    tokens = math.min(capacity, tokens + delta * refill_rate)
    last_updated = now
end

if tokens >= cost then
    tokens = tokens - cost
    redis.call("HMSET", key, "tokens", tokens, "last_updated", last_updated)
    redis.call("EXPIRE", key, math.ceil(capacity / refill_rate) * 2)
    return {1, math.floor(tokens), 0} -- {Allowed=1, Remaining, RetryAfter=0}
else
    local needed = cost - tokens
    local retry_after = math.ceil(needed / refill_rate)
    redis.call("HMSET", key, "tokens", tokens, "last_updated", last_updated)
    return {0, math.floor(tokens), retry_after} -- {Allowed=0, Remaining, RetryAfter}
end

"""

async def evluate_rate_limit(redis_client,
                             identifier: str,
                             limit: int = 60,
                             window_seconds: int = 60,
                             cost: int = 1) -> tuple[bool, int, int]:
    """
    Evaluate the rate limit for a given tenant using Redis.
    Returns a tuple of (allowed: bool, remaining: int, retry_after: int).
    Evalutes the rate limit using a Lua script to ensure atomicity via EVALSHA"""
    key = f"ratelimit:{identifier}"
    refill_rate = limit / window_seconds
    now = time.time()

    #1. Register the Lua script with Redis and get its SHA1 hash
    lua_runner = redis_client.register_script(TOKEN_BUCKET_LUA_SCRIPT)
    
    try:
        #2. Call the scripts:
        #   - First attempts to send EVALSHA with the SHA1 hash of the script.
        #   - If the script is not found (e.g., Redis restarted), it falls
        #     back to sending the full script with EVAL.
        result = await lua_runner(keys=[key],
                                    args=[limit, refill_rate, now, cost]
                                    )
        allowed, remaining, retry_after = bool(result[0]), int(result[1]), int(result[2])
        return allowed, remaining, retry_after

    except Exception as e:
        logger.warning(f"Redis error while evaluating rate limit for tenant {key}: {e}")

        if settings.RATE_LIMIT_FAIL_OPEN:
            logger.info(f"Fail-open enabled. Allowing request for tenant {key} despite Redis error.")
            return True, limit, 0  # Allow the request, no remaining limit, no retry after
        else:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Rate limtiting service unavailable. Request Rejected due to Redis error."
            )


class InMemoryTokenBucketRateLimiter(BaseHTTPMiddleware):
    def __init__(self, app, rate_limit: int = 60, window_seconds: int = 60):
        super().__init__(app)
        self.rate_limit = rate_limit
        self.window_seconds = window_seconds
        self.clients = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        # Exclude health and metrics from rate limiting
        if request.url.path in ["/healthz", "/readyz", "/metrics", "/docs", "/openapi.json"]:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        
        # Clean old timestamps
        timestamps = [t for t in self.clients[client_ip] if now - t < self.window_seconds]
        if len(timestamps) >= self.rate_limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Try again in 1 minute."
            )
            
        timestamps.append(now)
        self.clients[client_ip] = timestamps
        
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.rate_limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, self.rate_limit - len(timestamps)))
        return response


class RedisTokenBucketRateLimiter(BaseHTTPMiddleware):
    def __init__(self, app, rate_limit: int = 60, window_seconds: int = 60):
        super().__init__(app)
        self.rate_limit = rate_limit
        self.window_seconds = window_seconds

    async def dispatch(self, request: Request, call_next):
        # Exclude health and metrics from rate limiting
        if request.url.path in ["/healthz", "/readyz", "/metrics", "/docs", "/openapi.json"]:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"

        api_key = request.headers.get("X-API-Key")
        if api_key:
            hashed_key = hash_key(api_key)[:16]  # Use a truncated hash for privacy and uniqueness
            client_ip = f"tenant:{hashed_key}"
        else:
            client_ip = f"ip:{client_ip}"


        redis_client = get_redis_client()
        allowed, remaining, retry_after = await evluate_rate_limit(
            redis_client,
            identifier=client_ip,
            limit=self.rate_limit,
            window_seconds=self.window_seconds
        )

        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUEST,
                content="Too many requests",
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(self.rate_limit),
                    "X-RateLimit-Remaining": 0,
                         },
                detail=f"Rate limit exceeded. Try again in {retry_after} seconds."
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.rate_limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Retry-After"] = str(retry_after)
        return response