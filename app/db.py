import asyncpg

from config import settings

_pool: asyncpg.Pool | None = None


async def init_db_pool() -> asyncpg.Pool:
    """Create the global asyncpg connection pool."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn=settings.DATABASE_URL, min_size=1, max_size=10)
    return _pool


async def close_db_pool() -> None:
    """Close the global asyncpg connection pool if it is open."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_db_pool() -> asyncpg.Pool:
    """Return the current pool (must be used after init_db_pool)."""
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    return _pool
