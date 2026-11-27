import logging

from bot.client import MaxClient

logger = logging.getLogger("max-bot.handlers")

GREETING = "Привет! Ассистент логиста на связи."


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_chat_id(payload: dict) -> int | None:
    """Chat id is either at the top level (bot_started) or inside message.recipient."""
    chat_id = _as_int(payload.get("chat_id"))
    if chat_id is not None:
        return chat_id

    message = payload.get("message")
    if isinstance(message, dict):
        recipient = message.get("recipient")
        if isinstance(recipient, dict):
            chat_id = _as_int(recipient.get("chat_id"))
            if chat_id is not None:
                return chat_id
        chat_id = _as_int(message.get("chat_id"))
        if chat_id is not None:
            return chat_id
    return None


def _extract_text(payload: dict) -> str:
    message = payload.get("message")
    if not isinstance(message, dict):
        return ""
    body = message.get("body")
    if not isinstance(body, dict):
        return ""
    text = body.get("text")
    return text.strip() if isinstance(text, str) else ""


async def handle_update(payload: dict, max_client: MaxClient) -> None:
    """Handle an incoming MAX webhook update (flat Update object)."""
    update_type = payload.get("update_type")

    if update_type == "bot_started":
        chat_id = _extract_chat_id(payload)
        if chat_id is None:
            logger.warning("No chat_id in bot_started payload: %s", payload)
            return
        logger.info("bot_started in chat %s", chat_id)
        await max_client.send_message(chat_id, GREETING)
        return

    if update_type != "message_created":
        logger.debug("Ignoring update_type=%s", update_type)
        return

    text = _extract_text(payload)
    if not text.startswith("/start"):
        return

    chat_id = _extract_chat_id(payload)
    if chat_id is None:
        logger.warning("No chat_id in message_created payload: %s", payload)
        return

    logger.info("Replying to /start in chat %s", chat_id)
    await max_client.send_message(chat_id, GREETING)
