import logging

from bot.client import MaxClient
from bot.keyboards import main_menu_keyboard, tax_modes_keyboard
from services.users import TAX_LABELS, get_or_create_user, set_user_tax_mode

logger = logging.getLogger("max-bot.handlers")


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_chat_id(payload: dict) -> int | None:
    chat_id = _as_int(payload.get("chat_id"))
    if chat_id is not None:
        return chat_id
    message = payload.get("message")
    if isinstance(message, dict):
        recipient = message.get("recipient")
        if isinstance(recipient, dict) and (cid := _as_int(recipient.get("chat_id"))) is not None:
            return cid
        return _as_int(message.get("chat_id"))
    return None


def _extract_user_id(payload: dict) -> int | None:
    if isinstance(cb := payload.get("callback"), dict) and isinstance(usr := cb.get("user"), dict):
        if (uid := _as_int(usr.get("user_id"))) is not None:
            return uid
    for key in ("user", "sender"):
        if isinstance(obj := payload.get(key), dict) and (uid := _as_int(obj.get("user_id"))) is not None:
            return uid
    if isinstance(msg := payload.get("message"), dict) and isinstance(snd := msg.get("sender"), dict):
        if (uid := _as_int(snd.get("user_id"))) is not None:
            return uid
    return _extract_chat_id(payload)



def _extract_text(payload: dict) -> str:
    msg = payload.get("message")
    body = msg.get("body") if isinstance(msg, dict) else None
    text = body.get("text") if isinstance(body, dict) else None
    return text.strip() if isinstance(text, str) else ""


async def _send_welcome(chat_id: int, user_id: int, max_client: MaxClient) -> None:
    user = await get_or_create_user(user_id)
    current_tax = TAX_LABELS.get(user["tax_mode"], user["tax_mode"])
    text = (
        "Привет! Я «Ехали!» — карманный ассистент логиста.\n\n"
        "Помогу за 10 секунд посчитать чистую маржу с учётом НДС, "
        "пробить контрагента по ИНН и собрать ТТН от водителя.\n\n"
        f"Твой налоговый режим сейчас: {current_tax}.\n"
        "Если работаешь по другой системе — выбери ниже:"
    )
    await max_client.send_message(chat_id, text, buttons=main_menu_keyboard())


async def _handle_callback(payload: dict, max_client: MaxClient) -> None:
    cb = payload.get("callback")
    chat_id, user_id = _extract_chat_id(payload), _extract_user_id(payload)
    if not isinstance(cb, dict) or chat_id is None or user_id is None:
        return

    cb_id, data = cb.get("callback_id"), cb.get("payload", "")
    if not isinstance(data, str):
        return

    if data == "menu:tax":
        if isinstance(cb_id, str):
            await max_client.answer_callback(cb_id)
        await max_client.send_message(chat_id, "Выбери систему налогообложения:", buttons=tax_modes_keyboard())
    elif data.startswith("tax:"):
        tax_mode = data.split(":", 1)[1]
        try:
            await get_or_create_user(user_id)
            await set_user_tax_mode(user_id, tax_mode)
        except ValueError:
            return
        label = TAX_LABELS[tax_mode]
        if isinstance(cb_id, str):
            await max_client.answer_callback(cb_id, notification=f"Сохранено: {label}")
        await max_client.send_message(
            chat_id,
            f"Режим сохранён: {label}.\n\nПришли заявку одной строкой, например:\nнск омск 20т 140 с ндс / 100 ип подача 40",
        )
    elif data == "menu:help_calc":
        if isinstance(cb_id, str):
            await max_client.answer_callback(cb_id)
        await max_client.send_message(chat_id, "Пример заявки:\nнск омск 20т 140 с ндс / 100 ип подача 40\n(Калькулятор подключим следующим шагом!)")
    elif data == "menu:help_inn":
        if isinstance(cb_id, str):
            await max_client.answer_callback(cb_id)
        await max_client.send_message(chat_id, "Отправь 10 или 12 цифр ИНН контрагента — проверю ЕГРЮЛ и ГосЛог (подключим после калькулятора).")


async def handle_update(payload: dict, max_client: MaxClient) -> None:
    update_type = payload.get("update_type")
    if update_type == "bot_started":
        cid, uid = _extract_chat_id(payload), _extract_user_id(payload)
        if cid is not None and uid is not None:
            await _send_welcome(cid, uid, max_client)
    elif update_type == "message_callback":
        await _handle_callback(payload, max_client)
    elif update_type == "message_created" and _extract_text(payload).startswith("/start"):
        cid, uid = _extract_chat_id(payload), _extract_user_id(payload)
        if cid is not None and uid is not None:
            await _send_welcome(cid, uid, max_client)
