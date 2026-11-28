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
    weight_t NUMERIC(10, 2),
    deadhead_km NUMERIC(10, 2),
    client_rate NUMERIC(12, 2),
    client_vat BOOLEAN,
    carrier_rate NUMERIC(12, 2),
    carrier_vat BOOLEAN,
    margin NUMERIC(12, 2),
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE orders ADD COLUMN IF NOT EXISTS weight_t NUMERIC(10, 2);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS deadhead_km NUMERIC(10, 2);

CREATE INDEX IF NOT EXISTS idx_orders_user_created
    ON orders(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS user_states (
    user_id BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    state VARCHAR(64) NOT NULL DEFAULT 'idle',
    order_id INT REFERENCES orders(id) ON DELETE SET NULL,
    last_mid VARCHAR(128),
    last_text TEXT
);

ALTER TABLE user_states ADD COLUMN IF NOT EXISTS last_mid VARCHAR(128);
ALTER TABLE user_states ADD COLUMN IF NOT EXISTS last_text TEXT;

CREATE TABLE IF NOT EXISTS inn_cache (
    inn VARCHAR(12) PRIMARY KEY,
    payload JSONB NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


async def init_db_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn=settings.DATABASE_URL, min_size=1, max_size=10)
        async with _pool.acquire() as conn:
            await conn.execute(INIT_SQL)
    return _pool


async def close_db_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_db_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    return _pool
