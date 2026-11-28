from pathlib import Path
from uuid import uuid4

from bot.ui.keyboards import ttn_bad_photo_keyboard, ttn_driver_keyboard
from config import settings
from db import get_db_pool
from services.orders import (
    get_user_state,
    pop_pending_ttn_photo,
    set_pending_ttn_photo,
    set_user_state,
)
from services.ttn.ttn import _to_jpeg, check_photo_quality


def inspect_image(raw: bytes) -> list[str]:
    ok, reason = check_photo_quality(raw)
    return [] if ok else [reason]


async def has_pages(shipment_id: int) -> bool:
    async with get_db_pool().acquire() as conn:
        return bool(await conn.fetchval(
            "SELECT 1 FROM shipment_pages WHERE shipment_id = $1 LIMIT 1",
            shipment_id,
        ))


async def save_pending(driver_uid: int, shipment_id: int, raw: bytes) -> None:
    path = Path(settings.TTN_STORAGE_DIR) / str(shipment_id) / f"pending_{uuid4().hex}.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_to_jpeg(raw))
    await set_user_state(driver_uid, "wait_ttn_photo", order_id=shipment_id)
    await set_pending_ttn_photo(driver_uid, str(path))


async def remove_pending(driver_uid: int) -> None:
    if path := await pop_pending_ttn_photo(driver_uid):
        Path(path).unlink(missing_ok=True)


async def accept_pending(driver_user_id: int, shipment_id: int) -> tuple[str, list[list[dict]]]:
    state = await get_user_state(driver_user_id)
    if (state or {}).get("order_id") != shipment_id:
        return "⚠️ Не нашёл отложенное фото. Пришли его ещё раз.", ttn_driver_keyboard()
    path = await pop_pending_ttn_photo(driver_user_id)
    if not path:
        return "⚠️ Не нашёл отложенное фото. Пришли его ещё раз.", ttn_driver_keyboard()
    file_path = Path(path)
    if not file_path.is_file():
        return "⚠️ Отложенное фото больше недоступно. Пришли его ещё раз.", ttn_driver_keyboard()
    pool = get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            locked = await conn.fetchval(
                "SELECT id FROM shipments WHERE id = $1 AND driver_user_id = $2 "
                "AND status = 'waiting' FOR UPDATE",
                shipment_id,
                driver_user_id,
            )
            if locked is None:
                return "⚠️ Рейс не найден или уже закрыт.", ttn_driver_keyboard()
            page_num = await conn.fetchval(
                "SELECT COALESCE(MAX(page_num), 0) + 1 FROM shipment_pages WHERE shipment_id = $1",
                shipment_id,
            )
            page_path = file_path.with_name(f"page_{page_num}.jpg")
            file_path.replace(page_path)
            await conn.execute(
                "INSERT INTO shipment_pages (shipment_id, page_num, file_path) "
                "VALUES ($1, $2, $3)",
                shipment_id,
                page_num,
                str(page_path),
            )
    return f"✅ Фото приложено как лист №{page_num}.", ttn_driver_keyboard()
