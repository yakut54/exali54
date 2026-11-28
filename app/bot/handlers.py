import asyncio
import logging

from bot.client import MaxClient
from bot.keyboards import back_to_home_keyboard, main_menu_keyboard, tax_modes_keyboard
from bot.screens import screen_text
from bot.updates import edit_or_send, extract_chat_id, extract_msg_body, extract_user_id, send_fresh_menu
from services.calc_flow import build_calc_reply
from services.inn_flow import build_inn_reply, is_inn_text, is_order_text
from services.orders import clear_user_state, get_user_state, save_last_mid, set_user_state
from services.users import TAX_LABELS, get_or_create_user, set_user_tax_mode

logger = logging.getLogger("max-bot.handlers")


async def _handle_callback(payload: dict, max_client: MaxClient) -> None:
    cb = payload.get("callback")
    chat_id, user_id = extract_chat_id(payload), extract_user_id(payload)
    if not isinstance(cb, dict) or chat_id is None or user_id is None:
        return

    cb_id = cb.get("callback_id") if isinstance(cb.get("callback_id"), str) else None
    data = cb.get("payload", "")
    mid, old_text = extract_msg_body(payload)
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
        await edit_or_send(chat_id, user_id, mid, screen_text("home", tax), main_menu_keyboard(), max_client)
    elif data == "screen:tax":
        await edit_or_send(chat_id, user_id, mid, screen_text("tax", tax), tax_modes_keyboard(tax), max_client)
    elif data.startswith("tax:"):
        new_tax = data.removeprefix("tax:")
        try:
            await set_user_tax_mode(user_id, new_tax)
        except ValueError:
            return
        await edit_or_send(chat_id, user_id, mid, screen_text("tax", new_tax), tax_modes_keyboard(new_tax), max_client)
    elif data == "screen:inn":
        await set_user_state(user_id, "wait_inn")
        await edit_or_send(chat_id, user_id, mid, screen_text("inn", tax), back_to_home_keyboard(), max_client)
    elif data in ("screen:calc", "screen:ttn"):
        await clear_user_state(user_id)
        scr = data.removeprefix("screen:")
        await edit_or_send(chat_id, user_id, mid, screen_text(scr, tax), back_to_home_keyboard(), max_client)


async def handle_update(payload: dict, max_client: MaxClient) -> None:
    update_type = payload.get("update_type")
    if update_type in ("bot_started", "message_removed", "dialog_cleared"):
        cid, uid = extract_chat_id(payload), extract_user_id(payload)
        if uid is not None:
            await clear_user_state(uid)
            user = await get_or_create_user(uid)
            await send_fresh_menu(cid, uid, screen_text("home", user["tax_mode"]), main_menu_keyboard(), max_client, direct_uid=uid)
    elif update_type == "message_callback":
        await _handle_callback(payload, max_client)
    elif update_type == "message_created":
        cid, uid = extract_chat_id(payload), extract_user_id(payload)
        if cid is None or uid is None:
            return
        user = await get_or_create_user(uid)
        tax = user["tax_mode"]
        _, raw_text = extract_msg_body(payload)
        lower = raw_text.lower()

        if lower.startswith("/start"):
            await clear_user_state(uid)
            await send_fresh_menu(cid, uid, screen_text("home", tax), main_menu_keyboard(), max_client)
        elif lower.startswith("/tax"):
            await clear_user_state(uid)
            await send_fresh_menu(cid, uid, screen_text("tax", tax), tax_modes_keyboard(tax), max_client)
        elif lower.startswith("/inn"):
            await set_user_state(uid, "wait_inn")
            await send_fresh_menu(cid, uid, screen_text("inn", tax), back_to_home_keyboard(), max_client)
        elif lower.startswith("/calc"):
            await clear_user_state(uid)
            await send_fresh_menu(cid, uid, screen_text("calc", tax), back_to_home_keyboard(), max_client)
        elif raw_text:
            state = (await get_user_state(uid) or {}).get("state")
            if state == "wait_inn" and is_order_text(raw_text):
                await clear_user_state(uid)
                reply_text, kb = await build_calc_reply(uid, raw_text, tax)
            elif state == "wait_inn" or is_inn_text(raw_text):
                if state == "wait_inn":
                    await clear_user_state(uid)
                reply_text, kb = await build_inn_reply(raw_text)
            else:
                reply_text, kb = await build_calc_reply(uid, raw_text, tax)
            await send_fresh_menu(cid, uid, reply_text, kb, max_client)
