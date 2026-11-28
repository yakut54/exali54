import io
import secrets
from pathlib import Path

import img2pdf
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat

from config import settings
from db import get_db_pool

_SHIPMENT_FIELDS = "id, token, logist_user_id, logist_chat_id, driver_user_id, status"
A4_SIZE = (1654, 2339)


async def create_shipment(logist_user_id: int, logist_chat_id: int) -> str:
    token = secrets.token_hex(4)
    pool = get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO shipments (token, logist_user_id, logist_chat_id, status) "
            "VALUES ($1, $2, $3, 'waiting')",
            token,
            logist_user_id,
            logist_chat_id,
        )
    return token


def _normalize_token(token: str) -> str:
    return (token or "").strip().removeprefix("ttn_")


async def attach_driver_to_shipment(token: str, driver_user_id: int) -> dict | None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE shipments SET driver_user_id = $1 "
            "WHERE token = $2 AND status = 'waiting' "
            f"RETURNING {_SHIPMENT_FIELDS}",
            driver_user_id,
            _normalize_token(token),
        )
    return dict(row) if row else None


def check_photo_quality(image_bytes: bytes) -> tuple[bool, str]:
    with Image.open(io.BytesIO(image_bytes)) as img:
        gray = img.convert("L")
    if min(gray.size) < 600:
        return False, "Лист снят слишком далеко. Поднеси камеру ближе."
    brightness = ImageStat.Stat(gray).mean[0]
    if brightness < 45:
        return False, "Фото слишком тёмное. Добавь света и пересними лист."
    if brightness > 245:
        return False, "На фото сильный блик. Убери вспышку и пересними лист."
    edges = gray.filter(ImageFilter.FIND_EDGES)
    if ImageStat.Stat(edges).stddev[0] < 12.0:
        return False, "Фото размытое — текст не читается. Протри камеру и пересними лист."
    return True, "OK"


def _to_jpeg(image_bytes: bytes) -> bytes:
    with Image.open(io.BytesIO(image_bytes)) as img:
        rgb = ImageOps.autocontrast(ImageOps.exif_transpose(img).convert("RGB"), cutoff=2)
    rgb = rgb.transpose(Image.ROTATE_270) if rgb.width > rgb.height else rgb
    rgb = ImageEnhance.Sharpness(rgb).enhance(1.6)
    rgb = ImageEnhance.Contrast(rgb).enhance(1.25)
    resized = ImageOps.contain(rgb, A4_SIZE, Image.Resampling.LANCZOS)
    page = Image.new("RGB", A4_SIZE, "white")
    page.paste(resized, ((A4_SIZE[0] - resized.width) // 2, (A4_SIZE[1] - resized.height) // 2))
    page.save(out := io.BytesIO(), format="JPEG", quality=82, optimize=True)
    return out.getvalue()


async def add_shipment_page(shipment_id: int, image_bytes: bytes) -> int:
    ok, reason = check_photo_quality(image_bytes)
    if not ok:
        raise ValueError(reason)
    jpeg_bytes = _to_jpeg(image_bytes)
    pool = get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            locked = await conn.fetchval("SELECT id FROM shipments WHERE id = $1 FOR UPDATE", shipment_id)
            if locked is None:
                raise ValueError("Рейс не найден.")
            page_num = await conn.fetchval(
                "SELECT COALESCE(MAX(page_num), 0) + 1 FROM shipment_pages WHERE shipment_id = $1",
                shipment_id,
            )
            path = Path(settings.TTN_STORAGE_DIR) / str(shipment_id) / f"page_{page_num}.jpg"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(jpeg_bytes)
            await conn.execute(
                "INSERT INTO shipment_pages (shipment_id, page_num, file_path) VALUES ($1, $2, $3)",
                shipment_id,
                page_num,
                str(path),
            )
    return page_num


async def prepare_shipment_pdf(shipment_id: int, driver_user_id: int) -> tuple[dict, bytes] | None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT {_SHIPMENT_FIELDS} FROM shipments "
            "WHERE id = $1 AND driver_user_id = $2 AND status = 'waiting'",
            shipment_id,
            driver_user_id,
        )
        if row is None:
            return None
        rows = await conn.fetch(
            "SELECT file_path FROM shipment_pages WHERE shipment_id = $1 ORDER BY page_num ASC",
            shipment_id,
        )
    if not rows:
        raise ValueError("Сначала отправь хотя бы одну страницу ТТН.")
    paths = [
        Path(settings.TTN_STORAGE_DIR) / r["file_path"]
        if not Path(r["file_path"]).is_absolute()
        else Path(r["file_path"])
        for r in rows
    ]
    images_bytes = [path.read_bytes() for path in paths if path.is_file()]
    if not images_bytes:
        return dict(row), b""
    return dict(row), img2pdf.convert(images_bytes)


async def mark_shipment_completed(shipment_id: int) -> None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE shipments SET status = 'completed' WHERE id = $1", shipment_id)
