import logging

from bot.client import MaxClient

logger = logging.getLogger("max-bot.handlers")

GREETING = "Привет! Ассистент логиста на связи."


def _extract_chat_id(obj: dict) -> int | None:
    """Best-effort chat id lookup for MAX update objects."""
    message = obj.get("message")
    if isinstance(message, dict) and message.get("chat_id") is not None:
        return int(message["chat_id"])
    if obj.get("chat_id") is not None:
        return int(obj["chat_id"])
    return None


async def handle_update(payload: dict, max_client: MaxClient) -> None:
    """Handle an incoming MAX webhook update."""
    update_type = payload.get("update_type")
    obj = payload.get("object")
    if not isinstance(obj, dict):
        obj = {}

    if update_type == "bot_started":
        chat_id = _extract_chat_id(obj)
        if chat_id is not None:
            logger.info("bot_started in chat %s", chat_id)
            await max_client.send_message(chat_id, GREETING)
        return

    if update_type != "message_created":
        return

    message = obj.get("message")
    if not isinstance(message, dict):
        return

    text = (message.get("text") or "").strip()
    if text != "/start":
        return

    chat_id = _extract_chat_id(obj)
    if chat_id is None:
        logger.warning("No chat_id in message_created payload: %s", payload)
        return

    logger.info("Replying to /start in chat %s", chat_id)
    await max_client.send_message(chat_id, GREETING)
