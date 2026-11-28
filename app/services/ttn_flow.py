import httpx

from bot.client import MaxClient
from bot.keyboards import keep_result_menu_keyboard, ttn_driver_keyboard
from services.orders import clear_user_state, set_user_state
from services.ttn import (
    add_shipment_page,
    attach_driver_to_shipment,
    build_shipment_pdf,
    create_shipment,
)


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
    for url in image_urls:
        try:
            accepted.append(await add_shipment_page(shipment_id, await max_client.download_file(url)))
        except ValueError as exc:
            rejected.append(str(exc))
        except httpx.HTTPError:
            rejected.append("Не удалось скачать фото. Попробуй отправить ещё раз.")
    if not accepted:
        return "❌ Ни одна страница не принята:\n" + "\n".join(f"⚠️ {r}" for r in dict.fromkeys(rejected)), []
    lines = [f"✅ Принято страниц: {len(accepted)} (последняя — лист №{max(accepted)})",
             "Когда все страницы отправлены, нажми «✅ Готово»."]
    lines.extend(f"⚠️ {r}" for r in dict.fromkeys(rejected))
    return "\n".join(lines), ttn_driver_keyboard()


async def finish_driver_ttn(driver_uid: int, shipment_id: int, max_client: MaxClient) -> str:
    try:
        result = await build_shipment_pdf(shipment_id, driver_uid)
    except ValueError as exc:
        return str(exc)
    if result is None:
        return "⚠️ Рейс не найден или уже закрыт."
    shipment, pdf_bytes = result
    await max_client.send_document(
        shipment["logist_chat_id"],
        f"TTN_{shipment['token']}.pdf",
        pdf_bytes,
        caption=f"📄 **ТТН по рейсу `{shipment['token']}` готовы!**",
        buttons=keep_result_menu_keyboard(),
    )
    await clear_user_state(driver_uid)
    return "✅ Документы склеены в PDF и отправлены логисту! Спасибо."
