from db import get_db_pool

TAX_LABELS: dict[str, str] = {
    "osno_22": "ОСНО (с НДС 22%)",
    "usn_6": "УСН 6% (перевозка)",
    "usn_6_agent": "УСН 6% (агентский договор)",
    "usn_15": "УСН 15% (доходы-расходы)",
    "usn_5_nds": "УСН + НДС 5% (без вычета)",
}


async def get_or_create_user(user_id: int) -> dict:
    """Создать запись логиста в БД (если её нет) и вернуть его профиль."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users (user_id) VALUES ($1) ON CONFLICT (user_id) DO NOTHING",
            user_id,
        )
        row = await conn.fetchrow(
            "SELECT user_id, tax_mode, created_at FROM users WHERE user_id = $1",
            user_id,
        )
        return dict(row)


async def set_user_tax_mode(user_id: int, tax_mode: str) -> None:
    """Обновить систему налогообложения логиста."""
    if tax_mode not in TAX_LABELS:
        raise ValueError(f"Неизвестный налоговый режим: {tax_mode}")
    pool = get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET tax_mode = $1 WHERE user_id = $2",
            tax_mode,
            user_id,
        )
