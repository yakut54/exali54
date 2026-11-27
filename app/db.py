import asyncpg

from config import settings

_pool: asyncpg.Pool | None = None

INIT_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    tax_mode VARCHAR(32) NOT NULL DEFAULT 'osno_22',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    raw_text TEXT NOT NULL,
    route_from VARCHAR(128),
    route_to VARCHAR(128),
    cargo_date VARCHAR(64),
    cargo_info TEXT,
    body_type VARCHAR(64),
    client_rate NUMERIC(12, 2),
    client_vat BOOLEAN,
    carrier_rate NUMERIC(12, 2),
    carrier_vat BOOLEAN,
    margin NUMERIC(12, 2),
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orders_user_created
    ON orders(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS user_states (
    user_id BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    state VARCHAR(64) NOT NULL,
    order_id INT REFERENCES orders(id) ON DELETE SET NULL
);
"""


async def init_db_pool() -> asyncpg.Pool:
    """Create the global asyncpg connection pool and initialize tables."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn=settings.DATABASE_URL, min_size=1, max_size=10)
        async with _pool.acquire() as conn:
            await conn.execute(INIT_SQL)
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
