import asyncio
import logging

from bot.client import MaxClient
from bot.keyboards import back_to_home_keyboard, main_menu_keyboard, tax_modes_keyboard
from services.users import TAX_LABELS, get_or_create_user, set_user_tax_mode

logger = logging.getLogger("max-bot.handlers")


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_chat_id(payload: dict) -> int | None:
    if (cid := _as_int(payload.get("chat_id"))) is not None:
        return cid
    if isinstance(msg := payload.get("message"), dict):
        if isinstance(rec := msg.get("recipient"), dict) and (cid := _as_int(rec.get("chat_id"))) is not None:
            return cid
        return _as_int(msg.get("chat_id"))
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


def _extract_message_id(payload: dict) -> str | None:
    msg = payload.get("message")
    body = msg.get("body") if isinstance(msg, dict) else None
    mid = body.get("mid") if isinstance(body, dict) else None
    return mid if isinstance(mid, str) and mid else None


def _extract_text(payload: dict) -> str:
    msg = payload.get("message")
    body = msg.get("body") if isinstance(msg, dict) else None
    text = body.get("text") if isinstance(body, dict) else None
    return text.strip() if isinstance(text, str) else ""


def _home_text(tax_mode: str) -> str:
    tax_name = TAX_LABELS.get(tax_mode, tax_mode)
    return (
        "**🚛 Ехали! • Ассистент логиста**\n"
        f"Налог: **{tax_name}**\n\n"
        "Пришли параметры рейса или выбери инструмент:\n"
        "_(Если кнопки пропадут — просто напиши любое слово)_"
    )


async def _render_screen(
    chat_id: int, message_id: str | None, text: str, buttons: list[list[dict]], max_client: MaxClient
) -> None:
    if message_id:
        res = await max_client.edit_message(message_id, text, buttons=buttons)
        if res:
            return
    await max_client.send_message(chat_id, text, buttons=buttons)


async def _handle_callback(payload: dict, max_client: MaxClient) -> None:
    cb = payload.get("callback")
    chat_id, user_id = _extract_chat_id(payload), _extract_user_id(payload)
    if not isinstance(cb, dict) or chat_id is None or user_id is None:
        return

    cb_id = cb.get("callback_id") if isinstance(cb.get("callback_id"), str) else None
    data = cb.get("payload", "")
    mid = _extract_message_id(payload)
    if not isinstance(data, str):
        return

    if cb_id:
        toast = f"✅ {TAX_LABELS.get(data.removeprefix('tax:'), '')}" if data.startswith("tax:") else "⏳"
        asyncio.create_task(max_client.answer_callback(cb_id, notification=toast))

    user = await get_or_create_user(user_id)

    if data == "screen:home":
        await _render_screen(chat_id, mid, _home_text(user["tax_mode"]), main_menu_keyboard(), max_client)
    elif data == "screen:tax":
        text = f"**⚙️ Система налогообложения**\nСейчас: **{TAX_LABELS.get(user['tax_mode'], user['tax_mode'])}**"
        await _render_screen(chat_id, mid, text, tax_modes_keyboard(user["tax_mode"]), max_client)
    elif data.startswith("tax:"):
        tax_mode = data.removeprefix("tax:")
        try:
            await set_user_tax_mode(user_id, tax_mode)
        except ValueError:
            return
        text = f"**⚙️ Система налогообложения**\nСейчас: **{TAX_LABELS[tax_mode]}**"
        await _render_screen(chat_id, mid, text, tax_modes_keyboard(tax_mode), max_client)
    elif data == "screen:calc":
        text = (
            "**🧮 Стоп-цена и маржа**\n"
            "Напиши рейс одной строкой:\n"
            "`нск омск 20т 140 с ндс / 100 ип подача 40`"
        )
        await _render_screen(chat_id, mid, text, back_to_home_keyboard(), max_client)
    elif data == "screen:inn":
        text = "**🛡 Проверка ИНН**\nОтправь `10` или `12` цифр ИНН контрагента:"
        await _render_screen(chat_id, mid, text, back_to_home_keyboard(), max_client)
    elif data == "screen:ttn":
        text = "**📄 Сбор ТТН**\nСоздание ссылки для водителя (скоро)"
        await _render_screen(chat_id, mid, text, back_to_home_keyboard(), max_client)


async def handle_update(payload: dict, max_client: MaxClient) -> None:
    update_type = payload.get("update_type")
    if update_type == "bot_started":
        cid, uid = _extract_chat_id(payload), _extract_user_id(payload)
        if cid is not None and uid is not None:
            user = await get_or_create_user(uid)
            await max_client.send_message(cid, _home_text(user["tax_mode"]), buttons=main_menu_keyboard())
    elif update_type == "message_callback":
        await _handle_callback(payload, max_client)
    elif update_type == "message_created":
        cid, uid = _extract_chat_id(payload), _extract_user_id(payload)
        if cid is None or uid is None:
            return
        user = await get_or_create_user(uid)
        text = _extract_text(payload).lower()

        if text.startswith("/tax"):
            msg = f"**⚙️ Система налогообложения**\nСейчас: **{TAX_LABELS.get(user['tax_mode'], user['tax_mode'])}**"
            await max_client.send_message(cid, msg, buttons=tax_modes_keyboard(user["tax_mode"]))
        elif text.startswith("/calc"):
            msg = "**🧮 Стоп-цена и маржа**\nНапиши рейс одной строкой:\n`нск омск 20т 140 с ндс / 100 ип подача 40`"
            await max_client.send_message(cid, msg, buttons=back_to_home_keyboard())
        elif text.startswith("/inn"):
            msg = "**🛡 Проверка ИНН**\nОтправь `10` или `12` цифр ИНН контрагента:"
            await max_client.send_message(cid, msg, buttons=back_to_home_keyboard())
        else:
            await max_client.send_message(cid, _home_text(user["tax_mode"]), buttons=main_menu_keyboard())
