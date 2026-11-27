import logging

import httpx

from config import settings

logger = logging.getLogger("max-bot.client")

WEBHOOK_URL = settings.MAX_WEBHOOK_URL
UPDATE_TYPES = ["message_created", "bot_started"]


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

    async def set_webhook(self, url: str, secret: str | None = None) -> dict:
        """Subscribe the bot to webhook updates at the given URL."""
        body: dict = {
            "url": url,
            "update_types": UPDATE_TYPES,
        }
        if secret:
            body["secret"] = secret

        response = await self._client.post("/subscriptions", json=body)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and data.get("success") is False:
            raise RuntimeError(f"MAX rejected webhook subscription: {data}")
        return data

    async def get_subscriptions(self) -> list[dict]:
        """Return the list of active webhook subscriptions."""
        response = await self._client.get("/subscriptions")
        response.raise_for_status()
        data = response.json()
        subscriptions = data.get("subscriptions") if isinstance(data, dict) else None
        return subscriptions or []

    async def delete_subscription(self, url: str) -> dict:
        """Remove a webhook subscription by its URL."""
        response = await self._client.delete("/subscriptions", params={"url": url})
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and data.get("success") is False:
            logger.warning("MAX failed to delete subscription %s: %s", url, data)
        return data

    async def ensure_webhook(self, url: str, secret: str | None = None) -> dict:
        """Recreate the webhook subscription so URL/secret/update_types always match config."""
        subscriptions = await self.get_subscriptions()
        for subscription in subscriptions:
            old_url = subscription.get("url") if isinstance(subscription, dict) else None
            if not old_url:
                logger.warning("Skipping subscription without url: %s", subscription)
                continue
            logger.info("Removing existing webhook subscription %s", old_url)
            await self.delete_subscription(old_url)

        result = await self.set_webhook(url, secret)
        logger.info("Webhook subscription created: %s", result)
        return result

    async def aclose(self) -> None:
        await self._client.aclose()
