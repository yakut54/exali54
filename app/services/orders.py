from decimal import Decimal

from db import get_db_pool
from services.parser import ParsedOrder


async def set_user_state(user_id: int, state: str, order_id: int | None = None) -> None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_states (user_id, state, order_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO UPDATE
                SET state = EXCLUDED.state,
                    order_id = EXCLUDED.order_id
            """,
            user_id,
            state,
            order_id,
        )


async def get_user_state(user_id: int) -> dict | None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, state, order_id, last_mid, last_text FROM user_states WHERE user_id = $1",
            user_id,
        )
        return dict(row) if row else None


async def clear_user_state(user_id: int) -> None:
    await set_user_state(user_id, "idle", None)


async def save_last_mid(user_id: int, mid: str | None, text: str | None = None) -> None:
    if not mid:
        return
    pool = get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_states (user_id, state, last_mid, last_text)
            VALUES ($1, 'idle', $2, $3)
            ON CONFLICT (user_id) DO UPDATE
                SET last_mid = EXCLUDED.last_mid,
                    last_text = EXCLUDED.last_text
            """,
            user_id,
            mid,
            text,
        )


async def create_order(
    user_id: int,
    raw_text: str,
    parsed: ParsedOrder,
    client_rate: Decimal,
    client_vat: bool | None,
    margin: Decimal | None = None,
    status: str = "draft",
) -> int:
    cargo_parts = []
    if parsed.weight_t is not None:
        cargo_parts.append(f"{parsed.weight_t:g} т")
    if parsed.deadhead_km is not None:
        cargo_parts.append(f"подача {parsed.deadhead_km:g} км")
    cargo_info = ", ".join(cargo_parts) or None

    pool = get_db_pool()
    async with pool.acquire() as conn:
        order_id = await conn.fetchval(
            """
            INSERT INTO orders (
                user_id, raw_text, route_from, route_to, cargo_info,
                client_rate, client_vat, carrier_rate, carrier_vat, margin, status
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            RETURNING id
            """,
            user_id,
            raw_text,
            parsed.from_city,
            parsed.to_city,
            cargo_info,
            client_rate,
            client_vat,
            parsed.carrier_rate,
            parsed.carrier_vat,
            margin,
            status,
        )
        return int(order_id)


async def get_order(order_id: int, user_id: int) -> dict | None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM orders WHERE id = $1 AND user_id = $2",
            order_id,
            user_id,
        )
        return dict(row) if row else None


async def complete_order_carrier(
    order_id: int,
    carrier_rate: Decimal,
    carrier_vat: bool | None,
    margin: Decimal,
) -> None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE orders
               SET carrier_rate = $1,
                   carrier_vat = $2,
                   margin = $3,
                   status = 'calculated'
             WHERE id = $4
            """,
            carrier_rate,
            carrier_vat,
            margin,
            order_id,
        )
