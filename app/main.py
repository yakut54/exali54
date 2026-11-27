import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from bot.client import WEBHOOK_URL, MaxClient
from bot.handlers import handle_update
from db import close_db_pool, init_db_pool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("max-bot")

max_client = MaxClient()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db_pool()
    logger.info("Database pool started")
    yield
    await max_client.aclose()
    await close_db_pool()
    logger.info("Database pool closed")


app = FastAPI(title="MAX Bot", lifespan=lifespan)


@app.get("/")
async def healthcheck():
    return {"status": "ok", "service": "max-bot"}


@app.post("/webhook")
async def webhook(payload: dict):
    logger.info("Webhook received: %s", payload)
    try:
        await handle_update(payload, max_client)
    except Exception:
        logger.exception("Failed to handle update: %s", payload)
    return {"ok": True}


@app.post("/setup-webhook")
async def setup_webhook():
    logger.info("Registering webhook %s", WEBHOOK_URL)
    try:
        result = await max_client.set_webhook(WEBHOOK_URL)
    except Exception:
        logger.exception("Failed to register webhook")
        return {"ok": False, "url": WEBHOOK_URL}
    logger.info("Webhook registered: %s", result)
    return {"ok": True, "url": WEBHOOK_URL, "result": result}
