import json
import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
import httpx
from config import settings
from services.cities_dict import CITY_ALIASES, CITY_NORM_MAP, has_known_cities, normalize_city_name
from services.distance import get_road_distance_km
logger = logging.getLogger("max-bot.parser")
_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "order_parser.txt"
SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8").strip()
@dataclass(frozen=True)
class ParsedOrder:
    from_city: str | None
    to_city: str | None
    weight_t: Decimal | None
    client_rate: Decimal | None
    client_vat: bool | None
    carrier_rate: Decimal | None = None
    carrier_vat: bool | None = None
    client_alt_rate: Decimal | None = None
    client_alt_vat: bool | None = None
    deadhead_km: Decimal | None = None
    calc_mode: str = "margin"
    is_cash: bool = False
    distance_km: int | None = None
    client_rate_type: str = "total"
    cargo_name: str | None = None
    body_type: str | None = None
    cargo_date: str | None = None
    target_profit: Decimal | None = None
    warnings: list[str] = field(default_factory=list)
def _looks_like_order(text: str, in_dist_mode: bool = False) -> bool:
    if in_dist_mode:
        words = re.findall(r"[а-яё-]+", text.lower())
        return 3 <= len(text) <= 200 and len(words) >= 2 and text.lower().strip() not in {"привет", "здравствуйте", "добрый день"}
    numbers = re.findall(r"\d+(?:[.,]\d+)?", text)
    if len(text) > 1500:
        return False
    parts = text.lower().split()
    cities_only = re.fullmatch(r"[А-ЯЁ][а-яё-]+[ -]+[А-ЯЁ][а-яё-]+", text.strip())
    short_route = len(parts) == 2 and all(part in CITY_ALIASES for part in parts)
    phrase_route = bool(re.fullmatch(r"[а-яё-]+(?:\s+[а-яё-]+){1,6}", text.lower().strip()))
    return (bool(numbers) or has_known_cities(text) or bool(cities_only) or short_route or
            (phrase_route and not re.search(r"\b(и|или|от|до|на|из|в)\b", text.lower())) or
            bool(re.search(r"\b(км|километр|расстояни|пробег)\b", text.lower())))


def extract_two_cities(text: str) -> tuple[str, str] | None:
    words = text.strip().split()
    if len(words) < 2 or len(words) > 6:
        return None
    for split in range(1, len(words)):
        left, right = " ".join(words[:split]), " ".join(words[split:])
        keys = [
            " ".join(value.lower().replace("ё", "е").replace("-", " ").split())
            for value in (left, right)
        ]
        if all(key in CITY_ALIASES or key in CITY_NORM_MAP for key in keys):
            return normalize_city_name(left), normalize_city_name(right)
    if re.search(r"\d", text):
        prefix = text[:re.search(r"\d", text).start()]
        words = [word.strip(" ,;:-") for word in prefix.split()
                 if word.lower() not in {"из", "в", "до", "от", "на", "по"}]
        if len(words) == 2 and all(words):
            return normalize_city_name(words[0]), normalize_city_name(words[1])
    return None


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
def _normalize_rate(raw: Decimal | None, rate_type: str, weight_t: Decimal | None, distance_km: int | None, warnings: list[str], text: str) -> Decimal | None:
    if raw is None or raw <= 0:
        return None
    if rate_type == "per_ton":
        if weight_t and weight_t > 0:
            return raw * weight_t
        warnings.append("Цена указана за тонну, но вес не найден")
        return None
    if rate_type == "per_km":
        if distance_km and distance_km > 0:
            return raw * distance_km
        warnings.append("Ставка за км — требуется общий пробег")
        return raw
    short_total = rate_type == "total" and Decimal("15") <= raw < Decimal("2000") and not re.search(r"(?:км|р\s*/\s*км|за\s+км)", text.lower())
    return raw * Decimal("1000") if short_total or raw < Decimal("1000") else raw


def _rate_hint(text: str) -> tuple[Decimal, str, bool | None] | None:
    """Extract an unambiguous client-rate candidate from a short message."""
    lowered = text.lower()
    for match in re.finditer(r"(?<![\d/])(\d+(?:[.,]\d+)?)\s*(тыс|к|кг|т|м3|м²)?", lowered):
        raw_text, suffix = match.group(1), match.group(2) or ""
        tail = lowered[match.end():match.end() + 3]
        if (suffix in {"кг", "т", "м3", "м²"} or
                tail.startswith(("кг", "т", "м3", "м²")) or
                re.match(r"[./]\s*\d", tail)):
            continue
        raw = _to_decimal(raw_text)
        if raw is None:
            continue
        window = lowered[max(0, match.start() - 20):match.end() + 20]
        rate_type = "per_km" if re.search(r"(?:км|р\s*/\s*км|руб(?:лей)?\s*/\s*км|за\s+км|по\s+км)", window) else "total"
        vat = True if re.search(r"(?:ндс|осно)", window) else None
        return raw, rate_type, vat
    return None


async def parse_order_text(text: str, in_dist_mode: bool = False) -> ParsedOrder | None:
    if not _looks_like_order(text, in_dist_mode):
        return None
    if not re.search(r"\d", text):
        route = extract_two_cities(text)
        if route:
            distance = await get_road_distance_km(*route)
            return ParsedOrder(
                from_city=route[0], to_city=route[1], weight_t=None,
                client_rate=None, client_vat=None,
                distance_km=distance[0] if distance else None,
            )
    if not settings.DEEPSEEK_API_KEY:
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
            content = next(iter(choices)).get("message", {}).get("content", "")
            data = json.loads(content)
    except Exception as exc:
        logger.warning("Failed to parse order via LLM: %s", exc)
        return None
    raw_warnings = data.get("warnings")
    warnings = [str(w) for w in raw_warnings if w] if isinstance(raw_warnings, list) else []
    weight_t = _to_decimal(data.get("weight_t"))
    if weight_t is not None and weight_t <= 0:
        weight_t = None
    from_city = data.get("from_city") if isinstance(data.get("from_city"), str) else None
    to_city = data.get("to_city") if isinstance(data.get("to_city"), str) else None
    fallback_route = extract_two_cities(text)
    if fallback_route:
        from_city = from_city or fallback_route[0]
        to_city = to_city or fallback_route[1]
    distance = await get_road_distance_km(from_city, to_city) if from_city and to_city else None
    distance_km = distance[0] if distance else None
    c_type = data.get("client_rate_type") if data.get("client_rate_type") in ("total", "per_ton", "per_km") else "total"
    p_type = data.get("carrier_rate_type") if data.get("carrier_rate_type") in ("total", "per_ton", "per_km") else "total"
    client_raw = _to_decimal(data.get("client_rate_raw"))
    hint = _rate_hint(text)
    has_km_marker = bool(re.search(r"(?:км|р\s*/\s*км|за\s+км|по\s+км)", text.lower()))
    if not has_km_marker and c_type == "per_km":
        c_type = "total"
    if client_raw is None and hint:
        client_raw, hinted_type, hinted_vat = hint
        c_type = hinted_type
        if hinted_vat is not None and data.get("client_vat") is None:
            data["client_vat"] = hinted_vat
    carrier_raw = _to_decimal(data.get("carrier_rate_raw"))
    target_profit = _normalize_rate(_to_decimal(data.get("target_profit_raw")), "total", weight_t, None, warnings, text)
    carrier_markers = r"\b(перевоз|перевозчик|водител|машин|ип|на\s+карт|нал)\w*"
    if target_profit is not None and client_raw and carrier_raw is None and re.search(carrier_markers, text.lower()):
        carrier_raw, client_raw, p_type = client_raw, None, c_type
    client_rate = _normalize_rate(client_raw, c_type, weight_t, distance_km, warnings, text)
    if client_rate is None and not (from_city and to_city):
        return None
    client_alt_rate = _normalize_rate(_to_decimal(data.get("client_alt_rate_raw")), c_type, weight_t, distance_km, warnings, text)
    carrier_rate = _normalize_rate(carrier_raw, p_type, weight_t, distance_km, warnings, text)
    deadhead_km = _to_decimal(data.get("deadhead_km"))
    if deadhead_km is not None and deadhead_km < 0:
        deadhead_km = None
    is_cash = bool(data.get("is_cash"))
    c_vat = data.get("client_vat") if isinstance(data.get("client_vat"), bool) else None
    if is_cash:
        c_vat = False
    c_alt_vat = data.get("client_alt_vat") if isinstance(data.get("client_alt_vat"), bool) else None
    p_vat = data.get("carrier_vat") if isinstance(data.get("carrier_vat"), bool) else None
    mode = data.get("calc_mode") if data.get("calc_mode") in ("margin", "rate_per_km") else "margin"
    return ParsedOrder(from_city, to_city, weight_t, client_rate, c_vat, carrier_rate, p_vat,
                       client_alt_rate, c_alt_vat, deadhead_km, mode, is_cash, distance_km, c_type,
                       data.get("cargo_name"), data.get("body_type"), data.get("cargo_date"),
                       target_profit, warnings)
