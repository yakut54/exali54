import asyncio
import logging

from bot.client import MaxClient
from bot.keyboards import back_to_home_keyboard, main_menu_keyboard, tax_modes_keyboard
from bot.screens import screen_text
from services.calc_flow import build_calc_reply
from services.orders import clear_user_state, get_user_state, save_last_mid
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


def _extract_msg_body(payload: dict) -> tuple[str | None, str]:
    msg = payload.get("message")
    body = msg.get("body") if isinstance(msg, dict) else None
    if not isinstance(body, dict):
        return None, ""
    mid = body.get("mid") if isinstance(body.get("mid"), str) and body.get("mid") else None
    text = body.get("text").strip() if isinstance(body.get("text"), str) else ""
    return mid, text


async def _send_fresh_menu(
    chat_id: int | None, user_id: int, text: str, buttons: list[list[dict]], max_client: MaxClient, direct_uid: int | None = None
) -> None:
    st = await get_user_state(user_id)
    if st and (old_mid := st.get("last_mid")) and (old_txt := st.get("last_text")):
        asyncio.create_task(max_client.edit_message(old_mid, old_txt, buttons=[]))
    resp = await max_client.send_message(chat_id, text, buttons=buttons, user_id=direct_uid)
    new_mid = ((resp.get("message") or {}).get("body") or {}).get("mid") if isinstance(resp, dict) else None
    if isinstance(new_mid, str) and new_mid:
        await save_last_mid(user_id, new_mid, text)


async def _edit_or_send(
    chat_id: int, user_id: int, mid: str | None, text: str, buttons: list[list[dict]], max_client: MaxClient
) -> None:
    if mid and await max_client.edit_message(mid, text, buttons=buttons):
        await save_last_mid(user_id, mid, text)
        return
    await _send_fresh_menu(chat_id, user_id, text, buttons, max_client)


async def _handle_callback(payload: dict, max_client: MaxClient) -> None:
    cb = payload.get("callback")
    chat_id, user_id = _extract_chat_id(payload), _extract_user_id(payload)
    if not isinstance(cb, dict) or chat_id is None or user_id is None:
        return

    cb_id = cb.get("callback_id") if isinstance(cb.get("callback_id"), str) else None
    data = cb.get("payload", "")
    mid, old_text = _extract_msg_body(payload)
    if not isinstance(data, str):
        return

    if cb_id:
        toast = f"✅ {TAX_LABELS.get(data.removeprefix('tax:'), '')}" if data.startswith("tax:") else "⏳"
        asyncio.create_task(max_client.answer_callback(cb_id, notification=toast))

    user = await get_or_create_user(user_id)
    tax = user["tax_mode"]

    if data == "screen:home_new":
        await clear_user_state(user_id)
        if mid and old_text:
            asyncio.create_task(max_client.edit_message(mid, old_text, buttons=[]))
        home_txt = screen_text("home", tax)
        resp = await max_client.send_message(chat_id, home_txt, buttons=main_menu_keyboard())
        new_mid = ((resp.get("message") or {}).get("body") or {}).get("mid") if isinstance(resp, dict) else None
        await save_last_mid(user_id, new_mid, home_txt)
    elif data == "screen:home":
        await clear_user_state(user_id)
        await _edit_or_send(chat_id, user_id, mid, screen_text("home", tax), main_menu_keyboard(), max_client)
    elif data == "screen:tax":
        await _edit_or_send(chat_id, user_id, mid, screen_text("tax", tax), tax_modes_keyboard(tax), max_client)
    elif data.startswith("tax:"):
        new_tax = data.removeprefix("tax:")
        try:
            await set_user_tax_mode(user_id, new_tax)
        except ValueError:
            return
        await _edit_or_send(chat_id, user_id, mid, screen_text("tax", new_tax), tax_modes_keyboard(new_tax), max_client)
    elif data in ("screen:calc", "screen:inn", "screen:ttn"):
        await clear_user_state(user_id)
        scr = data.removeprefix("screen:")
        await _edit_or_send(chat_id, user_id, mid, screen_text(scr, tax), back_to_home_keyboard(), max_client)


async def handle_update(payload: dict, max_client: MaxClient) -> None:
    update_type = payload.get("update_type")
    if update_type in ("bot_started", "message_removed", "dialog_cleared"):
        cid, uid = _extract_chat_id(payload), _extract_user_id(payload)
        if uid is not None:
            await clear_user_state(uid)
            user = await get_or_create_user(uid)
            await _send_fresh_menu(cid, uid, screen_text("home", user["tax_mode"]), main_menu_keyboard(), max_client, direct_uid=uid)
    elif update_type == "message_callback":
        await _handle_callback(payload, max_client)
    elif update_type == "message_created":
        cid, uid = _extract_chat_id(payload), _extract_user_id(payload)
        if cid is None or uid is None:
            return
        user = await get_or_create_user(uid)
        tax = user["tax_mode"]
        _, raw_text = _extract_msg_body(payload)
        lower = raw_text.lower()

        if lower.startswith("/start"):
            await clear_user_state(uid)
            await _send_fresh_menu(cid, uid, screen_text("home", tax), main_menu_keyboard(), max_client)
        elif lower.startswith("/tax"):
            await clear_user_state(uid)
            await _send_fresh_menu(cid, uid, screen_text("tax", tax), tax_modes_keyboard(tax), max_client)
        elif lower.startswith("/calc") or lower.startswith("/inn"):
            await clear_user_state(uid)
            scr = "calc" if lower.startswith("/calc") else "inn"
            await _send_fresh_menu(cid, uid, screen_text(scr, tax), back_to_home_keyboard(), max_client)
        elif raw_text:
            reply_text, kb = await build_calc_reply(uid, raw_text, tax)
            await _send_fresh_menu(cid, uid, reply_text, kb, max_client)
