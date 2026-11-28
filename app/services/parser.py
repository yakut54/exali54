import json
import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

import httpx

from config import settings

logger = logging.getLogger("max-bot.parser")

DEEPSEEK_API_URL = "https://api.proxyapi.ru/v1/chat/completions"

SYSTEM_PROMPT = (
    "Ты строгий парсер заявок автомобильной грузоперевозок в РФ. Верни ТОЛЬКО валидный JSON без markdown и пояснений:\n"
    '{"from_city": str|null, "to_city": str|null, "weight_t": number|null, "rate_type": "total"|"per_ton"|"per_km", '
    '"client_rate_raw": number|null, "client_vat": bool|null, "carrier_rate_raw": number|null, "carrier_vat": bool|null, '
    '"deadhead_km": number|null, "warnings": list[str]}\n'
    "Правила извлечения:\n"
    "1) МАРШРУТ: Города и коды регионов приводи к полному названию (нск, новосиб, 54 -> Новосибирск; 55 -> Омск; "
    "екб, 66 -> Екатеринбург; челяба, 74 -> Челябинск; мск, 77 -> Москва; спб, питер, 78 -> Санкт-Петербург; "
    "крск, 24 -> Красноярск; ирк, 38 -> Иркутск; тюмень, 72 -> Тюмень; барнаул, 22 -> Барнаул; "
    "кемерово, 42 -> Кемерово; томск, 70 -> Томск; крд, 23 -> Краснодар; рнд, 61 -> Ростов-на-Дону; "
    "кзн, 16 -> Казань; нн, нижний, 52 -> Нижний Новгород; самара, 63 -> Самара; уфа, 02 -> Уфа; "
    "пермь, 59 -> Пермь; врн, 36 -> Воронеж; влг, 34 -> Волгоград; хбк, 27 -> Хабаровск; влд, 25 -> Владивосток). "
    "Складские зоны в скобках отбрасывай (МСК (Шушары) -> Москва). При кругорейсе (А - Б - А) to_city = Б.\n"
    "2) ВЕС (weight_t, в тоннах): фура, двадцатка, 20т, реф, тент, борт, шаланда -> 20; десятитонник, 10т -> 10; "
    "пятитонник, 5т -> 5; трехтонник, 3т -> 3; газель, полуторка -> 1.5. Кг переводи в тонны (500 кг -> 0.5). "
    "ИГНОРИРУЙ габариты кузова (13.6м, 82м3, 86 куб, 92, 120 куб), даты (28.11) и телефоны.\n"
    "3) СТАВКИ И ТИП: Если цена за тонну (р/т, за тонну) -> rate_type='per_ton'; за км (р/км) -> 'per_km'; иначе -> 'total'. "
    "Маркеры заказчика (client_rate_raw): вход, заказчик, дают, платит, нам, ставка. "
    "Маркеры перевозчика (carrier_rate_raw): выход, отдаю, отдам, перевоз, водителю, на руки. "
    "Если маркеров нет и даны 2 числа через /, -, на (140/100): первое = client_rate_raw, второе = carrier_rate_raw. "
    "ВАЖНО: если даны две ставки для ОДНОЙ стороны с разным НДС (например: 'заказчик 140 с ндс / 125 без ндс'), "
    "бери первый вариант в client_rate_raw, carrier_rate_raw = null, а в warnings добавь 'Указана вилка ставок по НДС'. "
    "Если оплата перевозчику разбита на части ('70 б/н + 30 на карту') -> суммируй (100), carrier_vat = false, в warnings напиши 'Комбинированная оплата'.\n"
    "4) ЧИСЛА: Убирай 'к', 'тыс', 'тр', 'руб', 'р', запятую меняй на точку, НЕ умножай на 1000 (140,5к -> 140.5; 140000 -> 140000). Налоги сам не считай.\n"
    "5) НДС: с ндс, ндс, +ндс, эндээс, осно -> true; без ндс, б/н без ндс, ип, усн, нал, на карту -> false; не указано -> null. "
    "Если НДС указан один раз в конце пары ('140 / 100 с ндс'), примени к обеим ставкам.\n"
    "6) ПОДАЧА (deadhead_km): Только километры ('подача 40', 'холостой 40км', 'подгон 40' -> 40). "
    "Если подача в рублях ('подача 5к') -> deadhead_km = null, в warnings добавь 'Подача указана в рублях'."
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
    warnings: list[str] = field(default_factory=list)


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
            resp = await client.post(DEEPSEEK_API_URL, headers=headers, json=body)
            resp.raise_for_status()
            choices = resp.json().get("choices") or []
            if not choices:
                return None
            content = choices[0].get("message", {}).get("content", "")
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
    carrier_rate = _normalize_rate(_to_decimal(data.get("carrier_rate_raw")), rate_type, weight_t, warnings)
    if client_rate is None or carrier_rate is None:
        return None

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
        warnings=warnings,
    )
