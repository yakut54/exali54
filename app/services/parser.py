import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

from config import settings

logger = logging.getLogger("max-bot.parser")

SYSTEM_PROMPT = (
    "Ты парсер заявок автомобильной грузоперевозки в РФ. Верни строго JSON без markdown-обёрток и комментариев со схемой: "
    '{"from_city": str|null, "to_city": str|null, "weight_t": number|null, "client_rate_raw": number|null, '
    '"client_vat": bool|null, "carrier_rate_raw": number|null, "carrier_vat": bool|null, "deadhead_km": number|null}. '
    "Правила: "
    "1) Названия городов и коды регионов РФ приводи к полному имени города "
    "(нск, новосиб, 54 -> Новосибирск; 55 -> Омск; екб, 66 -> Екатеринбург; челяба, 74 -> Челябинск; "
    "мск, 77 -> Москва; спб, питер, 78 -> Санкт-Петербург; крск, 24 -> Красноярск; ирк, 38 -> Иркутск; "
    "тюмень, 72 -> Тюмень; барнаул, 22 -> Барнаул; кемерово, 42 -> Кемерово; томск, 70 -> Томск; крд, 23 -> Краснодар). "
    "2) Вес: слова двадцатка, фура -> 20; десятитонник -> 10; пятитонник -> 5. "
    "3) Разделение ставок: первая ставка в паре (до слэша /, тире, слов на / отдаю / перевоз / выход) всегда client_rate_raw "
    "(ставка от заказчика). Вторая ставка (после /, на, отдаю, перевоз, выход, водителю) всегда carrier_rate_raw (ставка перевозчику). "
    "4) Не умножай числа и не считай налоги: пиши число ровно как в тексте (если 140 — пиши 140, если 140000 — пиши 140000). "
    "5) НДС: с ндс, ндс, с эндээс, осно -> true; без ндс, б/н без ндс, ип, усн, нал, на карту -> false; если не указано -> null. "
    "6) Подача, холостой, подгон, пустой пробег -> deadhead_km (в км)."
)


@dataclass(frozen=True)
class ParsedOrder:
    from_city: str | None
    to_city: str | None
    weight_t: Decimal | None
    client_rate: Decimal
    client_vat: bool | None
    carrier_rate: Decimal
    carrier_vat: bool | None
    deadhead_km: Decimal | None


def _looks_like_order(text: str) -> bool:
    numbers = re.findall(r"\d+(?:[.,]\d+)?", text)
    return len(numbers) >= 2 and len(text) <= 500


def _to_decimal(val) -> Decimal | None:
    if val is None or isinstance(val, bool):
        return None
    try:
        return Decimal(str(val).replace(",", ".").strip())
    except (InvalidOperation, ValueError):
        return None


def _normalize_rate(raw: Decimal | None) -> Decimal | None:
    if raw is None or raw <= 0:
        return None
    return raw * Decimal("1000") if raw < Decimal("1000") else raw


async def parse_order_text(text: str) -> ParsedOrder | None:
    if not _looks_like_order(text) or not settings.DEEPSEEK_API_KEY:
        return None

    base_url = settings.DEEPSEEK_BASE_URL.rstrip("/")
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
            resp = await client.post(f"{base_url}/chat/completions", headers=headers, json=body)
            resp.raise_for_status()
            choices = resp.json().get("choices") or []
            if not choices:
                return None
            content = choices.get("message", {}).get("content", "")
            data = json.loads(content)
    except Exception as exc:
        logger.warning("Failed to parse order via LLM: %s", exc)
        return None

    client_rate = _normalize_rate(_to_decimal(data.get("client_rate_raw")))
    carrier_rate = _normalize_rate(_to_decimal(data.get("carrier_rate_raw")))
    if client_rate is None or carrier_rate is None:
        return None

    weight_t = _to_decimal(data.get("weight_t"))
    if weight_t is not None and weight_t <= 0:
        weight_t = None

    deadhead_km = _to_decimal(data.get("deadhead_km"))
    if deadhead_km is not None and deadhead_km < 0:
        deadhead_km = None

    c_vat = data.get("client_vat") if isinstance(data.get("client_vat"), bool) else None
    p_vat = data.get("carrier_vat") if isinstance(data.get("carrier_vat"), bool) else None

    return ParsedOrder(
        from_city=data.get("from_city") if isinstance(data.get("from_city"), str) else None,
        to_city=data.get("to_city") if isinstance(data.get("to_city"), str) else None,
        weight_t=weight_t,
        client_rate=client_rate,
        client_vat=c_vat,
        carrier_rate=carrier_rate,
        carrier_vat=p_vat,
        deadhead_km=deadhead_km,
    )
