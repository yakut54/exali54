import logging
import httpx
from config import settings

logger = logging.getLogger("max-bot.client")

WEBHOOK_URL = settings.MAX_WEBHOOK_URL
UPDATE_TYPES = [
    "message_created",
    "bot_started",
    "message_callback",
    "message_removed",
    "dialog_cleared",
]


class MaxClient:
    """Thin HTTP client for the MAX platform API."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.MAX_API_URL,
            headers={"Authorization": settings.MAX_BOT_TOKEN},
            timeout=30.0,
        )

    def _build_body(self, text: str, buttons: list[list[dict]] | None) -> dict:
        body: dict = {"text": text, "format": "markdown"}
        if buttons is not None:
            body["attachments"] = (
                [{"type": "inline_keyboard", "payload": {"buttons": buttons}}] if buttons else []
            )
        return body

    async def send_message(
        self,
        chat_id: int | None,
        text: str,
        buttons: list[list[dict]] | None = None,
        user_id: int | None = None,
    ) -> dict:
        params: dict = {}
        if chat_id is not None:
            params["chat_id"] = chat_id
        elif user_id is not None:
            params["user_id"] = user_id
        else:
            raise ValueError("Either chat_id or user_id is required")

        response = await self._client.post(
            "/messages", params=params, json=self._build_body(text, buttons)
        )
        response.raise_for_status()
        return response.json()

    async def edit_message(
        self, message_id: str, text: str, buttons: list[list[dict]] | None = None
    ) -> dict:
        response = await self._client.put(
            "/messages", params={"message_id": message_id}, json=self._build_body(text, buttons)
        )
        if response.is_error:
            logger.warning("MAX PUT /messages failed (%s): %s", response.status_code, response.text)
            return {}
        return response.json()

    async def answer_callback(self, callback_id: str, notification: str | None = None) -> dict:
        if not notification:
            return {}
        response = await self._client.post(
            "/answers", params={"callback_id": callback_id}, json={"notification": notification}
        )
        if response.is_error:
            logger.warning("MAX /answers failed (%s): %s", response.status_code, response.text)
            return {}
        return response.json()

    async def set_commands(self) -> dict:
        commands = [
            {"name": "start", "description": "🏠 Главное меню"},
            {"name": "calc", "description": "🧮 Стоп-цена и маржа"},
            {"name": "inn", "description": "🛡 Проверить ИНН"},
            {"name": "tax", "description": "⚙️ Налоговый режим"},
        ]
        response = await self._client.patch("/me/commands", json={"commands": commands})
        if response.is_error:
            logger.warning("MAX PATCH /me/commands failed (%s): %s", response.status_code, response.text)
            return {}
        return response.json()

    async def set_webhook(self, url: str, secret: str | None = None) -> dict:
        body: dict = {"url": url, "update_types": UPDATE_TYPES}
        if secret:
            body["secret"] = secret
        response = await self._client.post("/subscriptions", json=body)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and data.get("success") is False:
            raise RuntimeError(f"MAX rejected webhook subscription: {data}")
        return data

    async def get_subscriptions(self) -> list[dict]:
        response = await self._client.get("/subscriptions")
        response.raise_for_status()
        data = response.json()
        return (data.get("subscriptions") if isinstance(data, dict) else None) or []

    async def delete_subscription(self, url: str) -> dict:
        response = await self._client.delete("/subscriptions", params={"url": url})
        response.raise_for_status()
        return response.json()

    async def ensure_webhook(self, url: str, secret: str | None = None) -> dict:
        for sub in await self.get_subscriptions():
            if isinstance(sub, dict) and (old_url := sub.get("url")):
                await self.delete_subscription(old_url)
        result = await self.set_webhook(url, secret)
        await self.set_commands()
        return result

    async def aclose(self) -> None:
        await self._client.aclose()
