import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from db import close_db_pool, init_db_pool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("max-bot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db_pool()
    logger.info("Database pool started")
    yield
    await close_db_pool()
    logger.info("Database pool closed")


app = FastAPI(title="MAX Bot", lifespan=lifespan)


@app.get("/")
async def healthcheck():
    return {"status": "ok", "service": "max-bot"}


@app.post("/webhook")
async def webhook(payload: dict):
    logger.info("Webhook received: %s", payload)
    return {"ok": True}
