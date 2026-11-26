import os
import pytest
import pytest_asyncio

# Default to local SQLite for product-independent unit tests when DATABASE_URL is not set
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_pulsestream.db"
if "REDIS_URL" not in os.environ:
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"

from app.database import engine, Base  # noqa: E402
import app.models  # noqa: E402,F401


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_test_database():
    """
    Initialize database schema once for the entire test session,
    and cleanly dispose connection pools when all tests complete.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

    if os.environ.get("DATABASE_URL", "").startswith("sqlite") and os.path.exists("./test_pulsestream.db"):
        os.remove("./test_pulsestream.db")
