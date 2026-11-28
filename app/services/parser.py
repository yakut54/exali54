import json
import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx

from config import settings

logger = logging.getLogger("max-bot.parser")

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "order_parser.txt"
SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8").strip()


@dataclass(frozen=True)
class ParsedOrder:
    from_city: str | None
    to_city: str | None
    weight_t: Decimal | None
    client_rate: Decimal
    client_vat: bool | None
    carrier_rate: Decimal | None = None
    carrier_vat: bool | None = None
    client_alt_rate: Decimal | None = None
    client_alt_vat: bool | None = None
    deadhead_km: Decimal | None = None
    warnings: list[str] = field(default_factory=list)


def _looks_like_order(text: str) -> bool:
    numbers = re.findall(r"\d+(?:[.,]\d+)?", text)
    return len(numbers) >= 1 and len(text) <= 1500


def _to_decimal(val) -> Decimal | None:
    if val is None or isinstance(val, bool):
        return None
    s = str(val).replace(" ", "").replace("\u00a0", "").strip()
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", s):
        s = s.replace(".", "")
    else:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _normalize_rate(
    raw: Decimal | None,
    rate_type: str,
    weight_t: Decimal | None,
    warnings: list[str],
) -> Decimal | None:
    if raw is None or raw <= 0:
        return None
    if rate_type == "per_ton":
        if weight_t and weight_t > 0:
            return raw * weight_t
        warnings.append("Цена указана за тонну, но вес не найден")
        return None
    if rate_type == "per_km":
        warnings.append("Ставка за км — требуется общий пробег")
        return None
    return raw * Decimal("1000") if raw < Decimal("1000") else raw


async def parse_order_text(text: str) -> ParsedOrder | None:
    if not _looks_like_order(text) or not settings.DEEPSEEK_API_KEY:
        return None

    headers = {"Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}"}
    body = {
        "model": "deepseek/deepseek-chat",
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(settings.DEEPSEEK_API_URL, headers=headers, json=body)
            resp.raise_for_status()
            choices = resp.json().get("choices") or []
            if not choices:
                return None
            content = choices.get("message", {}).get("content", "")
            data = json.loads(content)
    except Exception as exc:
        logger.warning("Failed to parse order via LLM: %s", exc)
        return None

    raw_warnings = data.get("warnings")
    warnings = [str(w) for w in raw_warnings if w] if isinstance(raw_warnings, list) else []

    weight_t = _to_decimal(data.get("weight_t"))
    if weight_t is not None and weight_t <= 0:
        weight_t = None

    rate_type = data.get("rate_type") if data.get("rate_type") in ("total", "per_ton", "per_km") else "total"

    client_rate = _normalize_rate(_to_decimal(data.get("client_rate_raw")), rate_type, weight_t, warnings)
    if client_rate is None:
        return None

    client_alt_rate = _normalize_rate(_to_decimal(data.get("client_alt_rate_raw")), rate_type, weight_t, warnings)
    carrier_rate = _normalize_rate(_to_decimal(data.get("carrier_rate_raw")), rate_type, weight_t, warnings)

    deadhead_km = _to_decimal(data.get("deadhead_km"))
    if deadhead_km is not None and deadhead_km < 0:
        deadhead_km = None

    c_vat = data.get("client_vat") if isinstance(data.get("client_vat"), bool) else None
    c_alt_vat = data.get("client_alt_vat") if isinstance(data.get("client_alt_vat"), bool) else None
    p_vat = data.get("carrier_vat") if isinstance(data.get("carrier_vat"), bool) else None

    return ParsedOrder(
        from_city=data.get("from_city") if isinstance(data.get("from_city"), str) else None,
        to_city=data.get("to_city") if isinstance(data.get("to_city"), str) else None,
        weight_t=weight_t,
        client_rate=client_rate,
        client_vat=c_vat,
        carrier_rate=carrier_rate,
        carrier_vat=p_vat,
        client_alt_rate=client_alt_rate,
        client_alt_vat=c_alt_vat,
        deadhead_km=deadhead_km,
        warnings=warnings,
    )
