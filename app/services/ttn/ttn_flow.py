import httpx
from pathlib import Path

from bot.transport.client import MaxClient
from bot.ui.keyboards import keep_result_menu_keyboard, ttn_bad_photo_keyboard, ttn_driver_keyboard
from config import settings
from db import get_db_pool
from services.orders import clear_user_state, get_user_state, set_user_state
from services.ttn.ttn import (
    add_shipment_page,
    attach_driver_to_shipment,
    create_shipment,
    mark_shipment_completed,
    prepare_shipment_pdf,
)
from services.ttn.ttn_pending import accept_pending as accept_pending_ttn_photo
from services.ttn.ttn_pending import has_pages, inspect_image, remove_pending, save_pending


async def start_ttn_for_logist(logist_uid: int, logist_cid: int, bot_username: str) -> tuple[str, list[list[dict]]]:
    token = await create_shipment(logist_uid, logist_cid)
    link = f"🔗 Ссылка для водителя: https://max.ru/{bot_username}?start=ttn_{token}" if bot_username else f"Код рейса: ttn_{token}"
    return (
        "**📄 Сбор ТТН**\n"
        f"{link}\n\n"
        "Отправь ссылку водителю. Он пришлёт фото страниц, а я соберу их в один PDF.",
        keep_result_menu_keyboard(),
    )


async def handle_driver_start(driver_uid: int, start_arg: str) -> str | None:
    if not (start_arg or "").startswith("ttn_"):
        return None
    shipment = await attach_driver_to_shipment(start_arg, driver_uid)
    if shipment is None:
        return "⚠️ Ссылка недействительна или этот рейс уже закрыт."
    await set_user_state(driver_uid, "wait_ttn_photo", order_id=shipment["id"])
    return "📸 **Сбор документов по рейсу**\nПришли чёткие фото всех страниц ТТН — по одному или несколько сразу."


async def handle_driver_photos(
    driver_uid: int, shipment_id: int, image_urls: list[str], max_client: MaxClient
) -> tuple[str, list[list[dict]]]:
    if not image_urls:
        return "📸 Пришли фото страниц ТТН или нажми «✅ Готово», когда закончишь.", ttn_driver_keyboard()
    accepted, rejected, pending_raw = [], [], None
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
            rejected.append("Не удалось загрузить фото. Пришли его ещё раз.")
    if pending_raw is not None:
        await remove_pending(driver_uid)
        await save_pending(driver_uid, shipment_id, pending_raw)
        text = "⚠️ **Фото не принято — его плохо видно:**\n"
        text += "\n".join(f"• {r}" for r in dict.fromkeys(rejected))
        text += "\n\nПересними лист при хорошем освещении. Если лучше снять не получается, нажми «Всё равно приложить»."
        return text, ttn_bad_photo_keyboard(await has_pages(shipment_id))
    if not accepted:
        return "❌ Не удалось принять ни одной страницы:\n" + "\n".join(f"⚠️ {r}" for r in dict.fromkeys(rejected)), []
    lines = [f"✅ Принято страниц: {len(accepted)} (последняя — лист №{max(accepted)})", "Когда всё отправишь, нажми «✅ Готово»."]
    lines.extend(f"⚠️ {r}" for r in dict.fromkeys(rejected))
    state = await get_user_state(driver_uid)
    keyboard = ttn_bad_photo_keyboard(True) if state and state.get("pending_photo_path") else ttn_driver_keyboard()
    return "\n".join(lines), keyboard


async def _page_files(shipment_id: int) -> list[str]:
    async with get_db_pool().acquire() as conn:
        rows = await conn.fetch("SELECT file_path FROM shipment_pages WHERE shipment_id = $1 ORDER BY page_num", shipment_id)
    return [str(Path(settings.TTN_STORAGE_DIR) / r["file_path"]) if not Path(r["file_path"]).is_absolute() else r["file_path"] for r in rows]


async def finish_driver_ttn(driver_uid: int, shipment_id: int, max_client: MaxClient) -> str:
    await remove_pending(driver_uid)
    try:
        paths = await _page_files(shipment_id)
        if not paths:
            return "⚠️ Не могу собрать PDF: пока нет ни одной страницы ТТН."
        if missing := [path for path in paths if not Path(path).is_file()]:
            return "⚠️ Не могу собрать PDF: файл одной из страниц не найден."
        result = await prepare_shipment_pdf(shipment_id, driver_uid)
    except ValueError as exc:
        return str(exc)
    except Exception:
        return "⚠️ Не удалось подготовить PDF. Пришли страницы ТТН ещё раз."
    if result is None:
        return "⚠️ Рейс не найден или уже закрыт."
    shipment, pdf_bytes = result
    if not pdf_bytes:
        return "⚠️ Не могу собрать PDF: файлы страниц не найдены."
    try:
        await max_client.send_document(shipment["logist_chat_id"], f"TTN_{shipment['token']}.pdf", pdf_bytes, caption=f"📄 **ТТН по рейсу `{shipment['token']}` готовы!**")
    except Exception:
        return "⚠️ Не удалось отправить PDF логисту. Нажми «✅ Готово» ещё раз."
    await mark_shipment_completed(shipment_id)
    await clear_user_state(driver_uid)
    return "✅ Готово. PDF отправлен логисту."
