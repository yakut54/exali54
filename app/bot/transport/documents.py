import asyncio
import logging

import httpx

logger = logging.getLogger("max-bot.documents")


async def download_file(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content


async def send_document(
    client: httpx.AsyncClient,
    chat_id: int,
    filename: str,
    file_bytes: bytes,
    caption: str = "",
    buttons: list[list[dict]] | None = None,
) -> dict:
    upload = await client.post("/uploads", params={"type": "file"})
    upload.raise_for_status()
    uploaded = await client.post(
        upload.json()["url"],
        files={"data": (filename, file_bytes, "application/pdf")},
    )
    uploaded.raise_for_status()
    await asyncio.sleep(0.8)
    attachments: list[dict] = [{"type": "file", "payload": uploaded.json()}]
    if buttons:
        attachments.append({"type": "inline_keyboard", "payload": {"buttons": buttons}})
    body = {"text": caption, "format": "markdown", "attachments": attachments}
    response = await client.post("/messages", params={"chat_id": chat_id}, json=body)
    for _ in range(2):
        if response.status_code != 400:
            break
        logger.warning("MAX file message failed (%s): %s", response.status_code, response.text)
        await asyncio.sleep(1.0)
        response = await client.post("/messages", params={"chat_id": chat_id}, json=body)
    response.raise_for_status()
    return response.json()
