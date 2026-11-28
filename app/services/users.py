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
    pool = get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO users (user_id) VALUES ($1) ON CONFLICT (user_id) DO NOTHING", user_id)
        row = await conn.fetchrow("SELECT user_id, tax_mode, paid_until, created_at FROM users WHERE user_id = $1", user_id)
        return dict(row)


async def set_user_tax_mode(user_id: int, tax_mode: str) -> None:
    if tax_mode not in TAX_LABELS:
        raise ValueError(f"Неизвестный налоговый режим: {tax_mode}")
    pool = get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET tax_mode = $1 WHERE user_id = $2", tax_mode, user_id)


async def is_free_beta_mode() -> bool:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT value FROM app_settings WHERE key = 'free_beta_mode'")
        return val != "false"


async def toggle_free_beta_mode() -> bool:
    new_bool = not await is_free_beta_mode()
    pool = get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO app_settings (key, value) VALUES ('free_beta_mode', $1) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            "true" if new_bool else "false",
        )
    return new_bool


async def check_and_inc_inn_limit(user_id: int) -> str | None:
    if user_id == settings.ADMIN_USER_ID:
        return None
    pool = get_db_pool()
    async with pool.acquire() as conn:
        free_beta = (await conn.fetchval("SELECT value FROM app_settings WHERE key = 'free_beta_mode'")) != "false"
        if free_beta:
            row = await conn.fetchrow(
                "UPDATE users SET inn_total_count = inn_total_count + 1, "
                "inn_daily_count = CASE WHEN inn_daily_date < CURRENT_DATE THEN 1 ELSE inn_daily_count + 1 END, "
                "inn_daily_date = CURRENT_DATE "
                "WHERE user_id = $1 AND (inn_daily_date < CURRENT_DATE OR inn_daily_count < $2) RETURNING user_id",
                user_id, settings.DAILY_INN_LIMIT,
            )
            return None if row else f"⚠️ Бета-тест: достигнут суточный лимит ({settings.DAILY_INN_LIMIT} проверок ИНН в день)."
        row = await conn.fetchrow(
            "UPDATE users SET inn_total_count = inn_total_count + 1 "
            "WHERE user_id = $1 AND ((paid_until IS NOT NULL AND paid_until > NOW()) OR inn_total_count < $2) RETURNING user_id",
            user_id, settings.FREE_TRIAL_INN_LIMIT,
        )
        if row:
            return None
        return f"🔒 Бесплатный пакет ({settings.FREE_TRIAL_INN_LIMIT} проверок ИНН) исчерпан.\nТариф Pro: **{settings.SUBSCRIPTION_PRICE_RUB} ₽ / мес** без лимитов."


async def is_calc_limit_exceeded(user_id: int) -> str | None:
    if user_id == settings.ADMIN_USER_ID:
        return None
    pool = get_db_pool()
    async with pool.acquire() as conn:
        free_beta = (await conn.fetchval("SELECT value FROM app_settings WHERE key = 'free_beta_mode'")) != "false"
        if free_beta:
            exceeded = await conn.fetchval(
                "SELECT COUNT(*) >= $2 FROM orders WHERE user_id = $1 AND created_at >= CURRENT_DATE",
                user_id, settings.DAILY_CALC_LIMIT,
            )
            return f"⚠️ Бета-тест: достигнут суточный лимит ({settings.DAILY_CALC_LIMIT} расчётов в день)." if exceeded else None
        is_pro = await conn.fetchval("SELECT paid_until IS NOT NULL AND paid_until > NOW() FROM users WHERE user_id = $1", user_id)
        if is_pro:
            return None
        used = await conn.fetchval("SELECT COUNT(*) FROM orders WHERE user_id = $1 AND status = 'calculated'", user_id)
        if used >= settings.FREE_TRIAL_CALC_LIMIT:
            return f"🔒 Бесплатный пакет ({settings.FREE_TRIAL_CALC_LIMIT} расчётов) исчерпан.\nТариф Pro: **{settings.SUBSCRIPTION_PRICE_RUB} ₽ / мес** без лимитов."
        return None


async def log_parse_failure(user_id: int, raw_text: str) -> None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO parse_failures (user_id, raw_text) VALUES ($1, $2)", user_id, raw_text)


async def get_all_user_ids() -> list[int]:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users ORDER BY user_id")
        return [r["user_id"] for r in rows]
