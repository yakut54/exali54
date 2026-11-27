import asyncio
import hmac
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from bot.client import WEBHOOK_URL, MaxClient
from bot.handlers import handle_update
from config import settings
from db import close_db_pool, init_db_pool

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("max-bot")

max_client = MaxClient()


async def _process_update(payload: dict) -> None:
    try:
        await handle_update(payload, max_client)
    except Exception:
        logger.exception("Failed to handle update: %s", payload)


async def _register_webhook_forever() -> None:
    """Register the webhook on startup and retry until MAX accepts it."""
    delay = 5
    while True:
        try:
            await max_client.ensure_webhook(
                WEBHOOK_URL,
                settings.MAX_WEBHOOK_SECRET or None,
            )
            logger.info("Webhook is ready: %s", WEBHOOK_URL)
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to register webhook, retrying in %ss", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 300)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db_pool()
    logger.info("Database pool started")

    registration_task = asyncio.create_task(
        _register_webhook_forever(), name="max-webhook-registration"
    )

    try:
        yield
    finally:
        registration_task.cancel()
        with suppress(asyncio.CancelledError):
            await registration_task
        logger.info("Webhook registration task stopped")

        await max_client.aclose()
        await close_db_pool()
        logger.info("Database pool closed")


app = FastAPI(title="MAX Bot", lifespan=lifespan)


@app.get("/")
async def healthcheck():
    return {"status": "ok", "service": "max-bot", "transport": "webhook"}


@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive MAX updates. MAX expects HTTP 200 within 30 seconds."""
    if settings.MAX_WEBHOOK_SECRET:
        provided = request.headers.get("X-Max-Bot-Api-Secret", "")
        if not hmac.compare_digest(provided, settings.MAX_WEBHOOK_SECRET):
            client = request.client.host if request.client else "unknown"
            logger.warning("Rejected webhook with invalid secret (client=%s)", client)
            raise HTTPException(status_code=403, detail="invalid secret")

    try:
        payload = await request.json()
    except Exception:
        logger.warning("Webhook body is not valid JSON")
        raise HTTPException(status_code=400, detail="invalid json")

    if not isinstance(payload, dict):
        logger.warning("Webhook body is not a JSON object: %r", payload)
        raise HTTPException(status_code=400, detail="invalid payload")

    logger.info("Webhook received: %s", payload)
    # Reply to MAX immediately; message processing happens after the response.
    background_tasks.add_task(_process_update, payload)
    return {"ok": True}


@app.post("/setup-webhook")
async def setup_webhook():
    """Recreate the webhook subscription from the current configuration."""
    try:
        result = await max_client.ensure_webhook(
            WEBHOOK_URL,
            settings.MAX_WEBHOOK_SECRET or None,
        )
    except Exception:
        logger.exception("Failed to register webhook")
        return JSONResponse(
            status_code=502,
            content={"ok": False, "url": WEBHOOK_URL},
        )
    return {"ok": True, "url": WEBHOOK_URL, "result": result}


@app.get("/webhook/status")
async def webhook_status():
    """Show the subscriptions MAX currently has for this bot."""
    try:
        subscriptions = await max_client.get_subscriptions()
    except Exception:
        logger.exception("Failed to fetch subscriptions")
        return JSONResponse(
            status_code=502,
            content={"ok": False, "url": WEBHOOK_URL},
        )
    return {"ok": True, "url": WEBHOOK_URL, "subscriptions": subscriptions}
