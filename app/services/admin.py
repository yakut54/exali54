import asyncio

from bot.client import MaxClient
from bot.keyboards import admin_keyboard, back_to_home_keyboard
from db import get_db_pool
from services.orders import set_user_state
from services.users import get_all_user_ids, is_free_beta_mode, toggle_free_beta_mode


def admin_panel_text(free_beta: bool) -> str:
    mode = "🟢 **Бесплатная бета**" if free_beta else "💳 **Платный режим**"
    return f"🛠 **Панель управления**\nРежим: {mode}\n\nВыбери действие:"


async def get_admin_stats() -> str:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                (SELECT COUNT(*) FROM users) AS users_total,
                (SELECT COUNT(*) FROM users WHERE created_at >= NOW() - INTERVAL '24 hours') AS users_new,
                (SELECT COUNT(*) FROM orders WHERE created_at >= NOW() - INTERVAL '24 hours') AS calc_day,
                (SELECT COUNT(*) FROM orders) AS calc_total,
                (SELECT COUNT(*) FROM inn_cache) AS inn_cached,
                (SELECT COUNT(*) FROM shipments WHERE status = 'completed') AS ttn_done
            """
        )
    return (
        "📊 **Сводка**\n"
        f"👥 Пользователи: {row['users_total']} · новых за 24 ч: {row['users_new']}\n"
        f"🧮 Расчёты: {row['calc_day']} за 24 ч · всего: {row['calc_total']}\n"
        f"🛡 Записей ИНН в кэше: {row['inn_cached']}\n"
        f"📄 Завершённых ТТН: {row['ttn_done']}"
    )


async def get_recent_failures(limit: int = 7) -> str:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT created_at, user_id, raw_text FROM parse_failures ORDER BY id DESC LIMIT $1",
            limit,
        )
    if not rows:
        return "✅ Нераспознанных запросов нет."
    lines = ["⚠️ **Последние нераспознанные заявки**"]
    for r in rows:
        text = " ".join((r["raw_text"] or "").split())[:120]
        lines.append(f"• {r['created_at']:%d.%m %H:%M} · `{r['user_id']}` — {text}")
    return "\n".join(lines)


async def run_broadcast(text: str, max_client: MaxClient) -> str:
    user_ids = await get_all_user_ids()
    ok = 0
    for uid in user_ids:
        try:
            await max_client.send_message(None, text, user_id=uid)
            ok += 1
        except Exception:
            pass
        await asyncio.sleep(0.05)
    return f"📢 Готово: сообщение доставлено {ok} из {len(user_ids)} пользователей."


async def admin_callback(user_id: int, data: str) -> tuple[str, list[list[dict]]]:
    if data == "admin:toggle_beta":
        free_beta = await toggle_free_beta_mode()
        return admin_panel_text(free_beta), admin_keyboard(free_beta)
    free_beta = await is_free_beta_mode()
    if data == "admin:stats":
        return await get_admin_stats(), admin_keyboard(free_beta)
    if data == "admin:fails":
        return await get_recent_failures(), admin_keyboard(free_beta)
    if data == "admin:broadcast":
        await set_user_state(user_id, "wait_broadcast")
        return "📢 **Рассылка**\nПришли текст сообщения одним сообщением:", back_to_home_keyboard()
    return admin_panel_text(free_beta), admin_keyboard(free_beta)
