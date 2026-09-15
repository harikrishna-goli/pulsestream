import pytest
import pytest_asyncio
from app.database import engine, Base
import app.models  # Ensure all SQLAlchemy models are registered with Base.metadata

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
