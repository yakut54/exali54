from config import settings
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


async def check_and_inc_inn_limit(user_id: int) -> bool:
    """Атомарно проверить и увеличить суточный счётчик проверок ИНН."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE users
               SET inn_daily_count = CASE WHEN inn_daily_date < CURRENT_DATE THEN 1 ELSE inn_daily_count + 1 END,
                   inn_daily_date = CURRENT_DATE
             WHERE user_id = $1
               AND (inn_daily_date < CURRENT_DATE OR inn_daily_count < $2)
            RETURNING inn_daily_count
            """,
            user_id,
            settings.DAILY_INN_LIMIT,
        )
        return row is not None


async def is_calc_limit_exceeded(user_id: int) -> bool:
    """Проверить, выбрал ли пользователь суточный лимит расчётов."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        return bool(await conn.fetchval(
            "SELECT COUNT(*) >= $2 FROM orders WHERE user_id = $1 AND created_at >= CURRENT_DATE",
            user_id,
            settings.DAILY_CALC_LIMIT,
        ))


async def log_parse_failure(user_id: int, raw_text: str) -> None:
    """Сохранить текст, который парсер не смог разобрать."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO parse_failures (user_id, raw_text) VALUES ($1, $2)",
            user_id,
            raw_text,
        )


async def get_all_user_ids() -> list[int]:
    """Вернуть ID всех пользователей бота для рассылки."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users ORDER BY user_id")
        return [r["user_id"] for r in rows]
