import httpx

from config import settings

WEBHOOK_URL = "https://exali54.ru/webhook"


class MaxClient:
    """Thin HTTP client for the MAX platform API."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.MAX_API_URL,
            headers={"Authorization": settings.MAX_BOT_TOKEN},
            timeout=30.0,
        )

    async def send_message(self, chat_id: int, text: str) -> dict:
        """Send a text message to a chat."""
        response = await self._client.post(
            "/messages",
            params={"chat_id": chat_id},
            json={"text": text},
        )
        response.raise_for_status()
        return response.json()

    async def set_webhook(self, url: str) -> dict:
        """Subscribe the bot to webhook updates at the given URL."""
        response = await self._client.post(
            "/subscriptions",
            json={
                "url": url,
                "update_types": ["message_created", "bot_started"],
            },
        )
        response.raise_for_status()
        return response.json()

    async def aclose(self) -> None:
        await self._client.aclose()
