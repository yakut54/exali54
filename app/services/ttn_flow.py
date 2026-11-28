import httpx
from pathlib import Path
from uuid import uuid4

from bot.client import MaxClient
from bot.keyboards import keep_result_menu_keyboard, ttn_bad_photo_keyboard, ttn_driver_keyboard
from config import settings
from db import get_db_pool
from services.orders import clear_user_state, get_user_state, pop_pending_ttn_photo, set_pending_ttn_photo, set_user_state
from services.ttn import (
    _to_jpeg,
    add_shipment_page,
    attach_driver_to_shipment,
    check_photo_quality,
    create_shipment,
    mark_shipment_completed,
    prepare_shipment_pdf,
)


def inspect_image(raw: bytes) -> list[str]:
    ok, reason = check_photo_quality(raw)
    return [] if ok else [reason]


async def _has_pages(shipment_id: int) -> bool:
    async with get_db_pool().acquire() as conn: return bool(await conn.fetchval("SELECT 1 FROM shipment_pages WHERE shipment_id = $1 LIMIT 1", shipment_id))


async def _save_pending(driver_uid: int, shipment_id: int, raw: bytes) -> None:
    path = Path(settings.TTN_STORAGE_DIR) / str(shipment_id) / f"pending_{uuid4().hex}.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_to_jpeg(raw))
    await set_user_state(driver_uid, "wait_ttn_photo", order_id=shipment_id)
    await set_pending_ttn_photo(driver_uid, str(path))


async def _remove_pending(driver_uid: int) -> None:
    if path := await pop_pending_ttn_photo(driver_uid):
        Path(path).unlink(missing_ok=True)


async def start_ttn_for_logist(logist_uid: int, logist_cid: int, bot_username: str) -> tuple[str, list[list[dict]]]:
    token = await create_shipment(logist_uid, logist_cid)
    if bot_username:
        link = f"🔗 Ссылка для водителя: https://max.ru/{bot_username}?start=ttn_{token}"
    else:
        link = f"Код рейса: ttn_{token} (укажите MAX_BOT_USERNAME в .env для прямой ссылки)"
    text = (
        "**📄 Сбор ТТН**\n"
        f"{link}\n\n"
        "Перешли ссылку водителю: он отправит фото страниц, а бот склеит их в PDF и пришлёт сюда."
    )
    return text, keep_result_menu_keyboard()


async def handle_driver_start(driver_uid: int, start_arg: str) -> str | None:
    if not (start_arg or "").startswith("ttn_"):
        return None
    shipment = await attach_driver_to_shipment(start_arg, driver_uid)
    if shipment is None:
        return "⚠️ Ссылка устарела или документы по этому рейсу уже сданы."
    await set_user_state(driver_uid, "wait_ttn_photo", order_id=shipment["id"])
    return ("📸 **Сбор документов по рейсу**\n"
            "Отправь чёткие фото всех страниц ТТН (по одному или сразу несколько):")


async def handle_driver_photos(
    driver_uid: int, shipment_id: int, image_urls: list[str], max_client: MaxClient
) -> tuple[str, list[list[dict]]]:
    if not image_urls:
        return "📸 Пришли фото страниц ТТН или нажми «✅ Готово».", ttn_driver_keyboard()
    accepted: list[int] = []
    rejected: list[str] = []
    pending_raw: bytes | None = None
    for url in image_urls:
        try:
            raw = await max_client.download_file(url)
            if warnings := inspect_image(raw):
                rejected.extend(warnings)
                pending_raw = raw
                continue
            accepted.append(await add_shipment_page(shipment_id, raw))
        except ValueError as exc:
            rejected.append(str(exc))
        except httpx.HTTPError:
            rejected.append("Не удалось скачать фото. Попробуй отправить ещё раз.")
    if pending_raw is not None:
        await _remove_pending(driver_uid)
        await _save_pending(driver_uid, shipment_id, pending_raw)
        text = "⚠️ **Фото не принято (плохо читается):**\n"
        text += "\n".join(f"• {r}" for r in dict.fromkeys(rejected))
        text += "\n\nСделай более чёткое фото при хорошем освещении и пришли его снова (или нажми «Всё равно приложить», если лучше снять не получается)."
        return text, ttn_bad_photo_keyboard(await _has_pages(shipment_id))
    if not accepted:
        return "❌ Ни одна страница не принята:\n" + "\n".join(f"⚠️ {r}" for r in dict.fromkeys(rejected)), []
    lines = [f"✅ Принято страниц: {len(accepted)} (последняя — лист №{max(accepted)})",
             "Когда все страницы отправлены, нажми «✅ Готово»."]
    lines.extend(f"⚠️ {r}" for r in dict.fromkeys(rejected))
    state = await get_user_state(driver_uid)
    keyboard = ttn_bad_photo_keyboard(True) if state and state.get("pending_photo_path") else ttn_driver_keyboard()
    return "\n".join(lines), keyboard


async def accept_pending_ttn_photo(driver_user_id: int, shipment_id: int) -> tuple[str, list[list[dict]]]:
    state = await get_user_state(driver_user_id)
    if (state or {}).get("order_id") != shipment_id:
        return "⚠️ Нет фотографии для принудительного добавления.", ttn_driver_keyboard()
    path = await pop_pending_ttn_photo(driver_user_id)
    if not path:
        return "⚠️ Нет фотографии для принудительного добавления.", ttn_driver_keyboard()
    file_path = Path(path)
    if not file_path.is_file():
        return "⚠️ Временное фото уже недоступно. Пришли его ещё раз.", ttn_driver_keyboard()
    pool = get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            locked = await conn.fetchval("SELECT id FROM shipments WHERE id = $1 AND driver_user_id = $2 AND status = 'waiting' FOR UPDATE", shipment_id, driver_user_id)
            if locked is None:
                return "⚠️ Рейс не найден или уже закрыт.", ttn_driver_keyboard()
            page_num = await conn.fetchval("SELECT COALESCE(MAX(page_num), 0) + 1 FROM shipment_pages WHERE shipment_id = $1", shipment_id)
            await conn.execute("INSERT INTO shipment_pages (shipment_id, page_num, file_path) VALUES ($1, $2, $3)", shipment_id, page_num, path)
    file_path.unlink(missing_ok=True)
    return f"✅ Фото приложено как лист №{page_num}.", ttn_driver_keyboard()


async def _page_files(shipment_id: int) -> list[str]:
    async with get_db_pool().acquire() as conn:
        rows = await conn.fetch("SELECT file_path FROM shipment_pages WHERE shipment_id = $1 ORDER BY page_num", shipment_id)
    return [
        str(Path(settings.TTN_STORAGE_DIR) / row["file_path"])
        if not Path(row["file_path"]).is_absolute() else row["file_path"]
        for row in rows
    ]


async def finish_driver_ttn(driver_uid: int, shipment_id: int, max_client: MaxClient) -> str:
    await _remove_pending(driver_uid)
    try:
        paths = await _page_files(shipment_id)
        if not paths:
            return "⚠️ Нельзя собрать PDF: ты ещё не отправил ни одного фото ТТН."
        missing = [path for path in paths if not Path(path).is_file()]
        if missing:
            return "⚠️ Нельзя собрать PDF: файл одной из страниц ТТН отсутствует на сервере."
        result = await prepare_shipment_pdf(shipment_id, driver_uid)
    except ValueError as exc:
        return str(exc)
    except Exception:
        return "⚠️ Не удалось подготовить PDF из-за ошибки файла. Пришли страницы ТТН ещё раз."
    if result is None:
        return "⚠️ Рейс не найден или уже закрыт."
    shipment, pdf_bytes = result
    if not pdf_bytes:
        return "⚠️ Не удалось собрать PDF: файлы страниц ТТН не найдены на сервере."
    try:
        await max_client.send_document(
            shipment["logist_chat_id"],
            f"TTN_{shipment['token']}.pdf",
            pdf_bytes,
            caption=f"📄 **ТТН по рейсу `{shipment['token']}` готовы!**",
        )
    except Exception:
        return "⚠️ Не удалось отправить PDF логисту. Попробуй нажать «✅ Готово» ещё раз."
    await mark_shipment_completed(shipment_id)
    await clear_user_state(driver_uid)
    return "✅ Документы склеены в PDF и отправлены логисту! Спасибо."
