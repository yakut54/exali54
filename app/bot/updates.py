import asyncio

from bot.client import MaxClient
from services.orders import get_user_state, save_last_mid


def as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def extract_chat_id(payload: dict) -> int | None:
    if (cid := as_int(payload.get("chat_id"))) is not None:
        return cid
    if isinstance(msg := payload.get("message"), dict):
        if isinstance(rec := msg.get("recipient"), dict) and (cid := as_int(rec.get("chat_id"))) is not None:
            return cid
        return as_int(msg.get("chat_id"))
    return None


def extract_user_id(payload: dict) -> int | None:
    if isinstance(cb := payload.get("callback"), dict) and isinstance(usr := cb.get("user"), dict):
        if (uid := as_int(usr.get("user_id"))) is not None:
            return uid
    for key in ("user", "sender"):
        if isinstance(obj := payload.get(key), dict) and (uid := as_int(obj.get("user_id"))) is not None:
            return uid
    if isinstance(msg := payload.get("message"), dict) and isinstance(snd := msg.get("sender"), dict):
        if (uid := as_int(snd.get("user_id"))) is not None:
            return uid
    return extract_chat_id(payload)


def extract_msg_body(payload: dict) -> tuple[str | None, str]:
    msg = payload.get("message")
    body = msg.get("body") if isinstance(msg, dict) else None
    if not isinstance(body, dict):
        return None, ""
    mid = body.get("mid") if isinstance(body.get("mid"), str) and body.get("mid") else None
    text = body.get("text").strip() if isinstance(body.get("text"), str) else ""
    return mid, text


async def send_fresh_menu(
    chat_id: int | None, user_id: int, text: str, buttons: list[list[dict]], max_client: MaxClient, direct_uid: int | None = None
) -> None:
    st = await get_user_state(user_id)
    if st and (old_mid := st.get("last_mid")) and (old_txt := st.get("last_text")):
        asyncio.create_task(max_client.edit_message(old_mid, old_txt, buttons=[]))
    resp = await max_client.send_message(chat_id, text, buttons=buttons, user_id=direct_uid)
    new_mid = ((resp.get("message") or {}).get("body") or {}).get("mid") if isinstance(resp, dict) else None
    if isinstance(new_mid, str) and new_mid:
        await save_last_mid(user_id, new_mid, text)


async def edit_or_send(
    chat_id: int, user_id: int, mid: str | None, text: str, buttons: list[list[dict]], max_client: MaxClient
) -> None:
    if mid and await max_client.edit_message(mid, text, buttons=buttons):
        await save_last_mid(user_id, mid, text)
        return
    await send_fresh_menu(chat_id, user_id, text, buttons, max_client)
