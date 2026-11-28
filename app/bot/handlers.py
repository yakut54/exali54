import asyncio
from bot.client import MaxClient
from bot.keyboards import admin_keyboard, back_to_home_keyboard, keep_result_menu_keyboard, main_menu_keyboard, tax_modes_keyboard, ttn_driver_keyboard
from bot.screens import screen_text
from bot.updates import edit_or_send, extract_chat_id, extract_image_urls, extract_msg_body, extract_start_payload, extract_user_id, send_fresh_menu, send_home_screen
from config import settings
from services.admin import admin_callback, admin_panel_text, run_broadcast
from services.calc_parse import format_cargo_post
from services.calc_flow import build_calc_reply, start_recalc_carrier
from services.inn_flow import build_inn_reply, is_inn_text, is_order_text
from services.orders import clear_user_state, get_order, get_user_state, set_user_state
from services.distance import get_road_distance_km
from services.ttn_flow import accept_pending_ttn_photo, finish_driver_ttn, handle_driver_photos, handle_driver_start, start_ttn_for_logist
from services.users import TAX_LABELS, get_or_create_user, is_free_beta_mode, set_user_tax_mode
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
    tax = (await get_or_create_user(user_id))["tax_mode"]
    if data == "screen:home_new":
        await send_home_screen(chat_id, user_id, mid, old_text, tax, max_client)
    elif data in ("screen:home", "screen:calc"):
        await clear_user_state(user_id)
        await edit_or_send(chat_id, user_id, mid, screen_text(data.removeprefix("screen:"), tax), main_menu_keyboard() if data == "screen:home" else back_to_home_keyboard(), max_client)
    elif data == "screen:dist":
        await set_user_state(user_id, "wait_dist")
        await edit_or_send(chat_id, user_id, mid, screen_text("dist", tax), back_to_home_keyboard(), max_client)
    elif data == "screen:tax":
        await edit_or_send(chat_id, user_id, mid, screen_text("tax", tax), tax_modes_keyboard(tax), max_client)
    elif data.startswith("tax:"):
        new_tax = data.removeprefix("tax:")
        if new_tax in TAX_LABELS:
            await set_user_tax_mode(user_id, new_tax)
            await edit_or_send(chat_id, user_id, mid, screen_text("tax", new_tax), tax_modes_keyboard(new_tax), max_client)
    elif data == "screen:inn":
        await set_user_state(user_id, "wait_inn")
        await edit_or_send(chat_id, user_id, mid, screen_text("inn", tax), back_to_home_keyboard(), max_client)
    elif data == "screen:ttn":
        reply, kb = await start_ttn_for_logist(user_id, chat_id, max_client.bot_username)
        await send_fresh_menu(chat_id, user_id, reply, kb, max_client)
    elif data in ("ttn:done", "ttn:force_last"):
        if mid and old_text:
            try:
                await max_client.edit_message(mid, old_text, [])
            except Exception:
                pass
        st = await get_user_state(user_id) or {}
        if st.get("state") != "wait_ttn_photo" or not st.get("order_id"):
            await send_fresh_menu(chat_id, user_id, "ℹ️ Этот рейс уже закрыт. PDF уже отправлен логисту.", keep_result_menu_keyboard(), max_client)
        elif data == "ttn:done":
            await send_fresh_menu(chat_id, user_id, await finish_driver_ttn(user_id, st["order_id"], max_client), keep_result_menu_keyboard(), max_client)
        else:
            reply, kb = await accept_pending_ttn_photo(user_id, st["order_id"])
            await send_fresh_menu(chat_id, user_id, reply, kb or ttn_driver_keyboard(), max_client)
    elif data.startswith("calc:recalc:") and data.removeprefix("calc:recalc:").isdigit():
        if reply := await start_recalc_carrier(user_id, int(data.removeprefix("calc:recalc:")), tax):
            await send_fresh_menu(chat_id, user_id, reply, back_to_home_keyboard(), max_client)
    elif data.startswith("calc:post:") and data.removeprefix("calc:post:").isdigit() and (order := await get_order(int(data.removeprefix("calc:post:")), user_id)):
        dist = await get_road_distance_km(order["route_from"], order["route_to"])
        await send_fresh_menu(chat_id, user_id, format_cargo_post(order, dist[0] if dist else None), keep_result_menu_keyboard(), max_client)
    elif data.startswith("admin:") and user_id == settings.ADMIN_USER_ID:
        reply, kb = await admin_callback(user_id, data)
        await edit_or_send(chat_id, user_id, mid, reply, kb, max_client)


async def handle_update(payload: dict, max_client: MaxClient) -> None:
    update_type = payload.get("update_type")
    if update_type in ("bot_started", "message_removed", "dialog_cleared"):
        cid, uid = extract_chat_id(payload), extract_user_id(payload)
        if uid is not None:
            await clear_user_state(uid)
            reply = await handle_driver_start(uid, extract_start_payload(payload))
            tax = (await get_or_create_user(uid))["tax_mode"]
            await send_fresh_menu(cid, uid, reply or screen_text("home", tax), [] if reply else main_menu_keyboard(), max_client, direct_uid=uid)
    elif update_type == "message_callback":
        await _handle_callback(payload, max_client)
    elif update_type == "message_created":
        cid, uid = extract_chat_id(payload), extract_user_id(payload)
        if cid is None or uid is None:
            return
        tax = (await get_or_create_user(uid))["tax_mode"]
        _, raw_text = extract_msg_body(payload)
        lower = raw_text.lower()

        if lower.startswith("/start"):
            await clear_user_state(uid)
            reply = await handle_driver_start(uid, extract_start_payload(payload))
            await send_fresh_menu(cid, uid, reply or screen_text("home", tax), [] if reply else main_menu_keyboard(), max_client)
        elif lower.startswith("/tax"):
            await clear_user_state(uid); await send_fresh_menu(cid, uid, screen_text("tax", tax), tax_modes_keyboard(tax), max_client)
        elif lower.startswith("/inn"):
            await set_user_state(uid, "wait_inn")
            await send_fresh_menu(cid, uid, screen_text("inn", tax), back_to_home_keyboard(), max_client)
        elif lower.startswith("/calc"):
            await clear_user_state(uid); await send_fresh_menu(cid, uid, screen_text("calc", tax), back_to_home_keyboard(), max_client)
        elif lower.startswith("/admin"):
            if uid != settings.ADMIN_USER_ID:
                return
            await clear_user_state(uid)
            free_beta = await is_free_beta_mode()
            await send_fresh_menu(cid, uid, admin_panel_text(free_beta), admin_keyboard(free_beta), max_client)
        elif (st := await get_user_state(uid) or {}).get("state") == "wait_ttn_photo" and st.get("order_id"):
            reply, kb = await handle_driver_photos(uid, st["order_id"], extract_image_urls(payload), max_client)
            await send_fresh_menu(cid, uid, reply, kb, max_client)
        elif st.get("state") == "wait_broadcast" and uid == settings.ADMIN_USER_ID and raw_text:
            await clear_user_state(uid)
            free_beta = await is_free_beta_mode()
            await send_fresh_menu(cid, uid, await run_broadcast(raw_text, max_client), admin_keyboard(free_beta), max_client)
        elif extract_image_urls(payload):
            await send_fresh_menu(cid, uid, "📷 Фото принимаю только в разделе **«📄 ТТН»** — по ссылке для водителя.\n\nЕсли это скриншот заявки или ИНН, пришли текст — я сразу помогу.", keep_result_menu_keyboard(), max_client)
        elif st.get("state") == "wait_dist" and raw_text:
            reply_text, kb = await build_calc_reply(uid, raw_text, tax, in_dist_mode=True)
            await send_fresh_menu(cid, uid, reply_text, kb, max_client)
        elif raw_text:
            if st.get("state") == "wait_inn" and is_order_text(raw_text):
                await clear_user_state(uid)
                reply_text, kb = await build_calc_reply(uid, raw_text, tax, in_dist_mode=st.get("state") == "wait_dist")
            elif st.get("state") == "wait_inn" or is_inn_text(raw_text):
                if st.get("state") == "wait_inn":
                    await clear_user_state(uid)
                reply_text, kb = await build_inn_reply(uid, raw_text)
            else:
                reply_text, kb = await build_calc_reply(uid, raw_text, tax, in_dist_mode=st.get("state") == "wait_dist")
            await send_fresh_menu(cid, uid, reply_text, kb, max_client)
        elif isinstance((body := (payload.get("message") or {}).get("body")), dict) and isinstance(body.get("attachments"), list) and body["attachments"]:
            await send_fresh_menu(cid, uid, "🎙 Голосовые, файлы и стикеры пока не читаю.\nПришли маршрут, ставку или ИНН текстом — я помогу.", keep_result_menu_keyboard(), max_client)
