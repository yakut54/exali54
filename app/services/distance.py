import math

import httpx

from config import settings
from db import get_db_pool

GEOCODE_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/address"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
CITY_ALIASES = {
    "мск": "Москва", "спб": "Санкт-Петербург", "питер": "Санкт-Петербург",
    "нск": "Новосибирск", "екб": "Екатеринбург", "кзн": "Казань",
    "крд": "Краснодар", "рнд": "Ростов-на-Дону", "нн": "Нижний Новгород",
    "члб": "Челябинск", "крск": "Красноярск", "тмн": "Тюмень",
    "прм": "Пермь", "брн": "Барнаул", "кем": "Кемерово",
    "нвкз": "Новокузнецк", "ирк": "Иркутск", "уу": "Улан-Удэ",
    "срг": "Сургут", "нврт": "Нижневартовск", "мгн": "Магнитогорск",
    "орб": "Оренбург", "смр": "Самара", "тлт": "Тольятти",
    "влг": "Волгоград", "врн": "Воронеж", "срт": "Саратов",
    "пнз": "Пенза", "улн": "Ульяновск", "иж": "Ижевск",
    "крв": "Киров", "ярик": "Ярославль", "ярсл": "Ярославль",
    "твр": "Тверь", "клг": "Калуга", "рзн": "Рязань",
    "блг": "Белгород", "лпц": "Липецк", "чбкс": "Чебоксары",
    "чебы": "Чебоксары", "ств": "Ставрополь", "нврс": "Новороссийск",
    "астр": "Астрахань", "мхч": "Махачкала", "клнг": "Калининград",
    "мурм": "Мурманск", "арх": "Архангельск", "влгд": "Волгодонск",
    "птз": "Петрозаводск", "влдв": "Владивосток", "влад": "Владивосток",
    "хбр": "Хабаровск", "блгв": "Благовещенск", "якт": "Якутск",
    "нхд": "Находка", "усс": "Уссурийск", "алмата": "Алматы",
}


def _clean(value: str | None) -> str:
    value = " ".join((value or "").lower().split())
    return CITY_ALIASES.get(value, value)


async def _cached(keys: tuple[str, str]) -> tuple[int, bool] | None:
    async with get_db_pool().acquire() as conn:
        row = await conn.fetchrow(
            "SELECT distance_km, is_approx FROM route_cache WHERE route_key = ANY($1::varchar[])",
            list(keys),
        )
    return (row["distance_km"], row["is_approx"]) if row else None


async def _geocode(client: httpx.AsyncClient, city: str) -> tuple[float, float] | None:
    response = await client.post(
        GEOCODE_URL,
        headers={"Authorization": f"Token {settings.DADATA_API_KEY}"},
        json={"query": city, "count": 1, "from_bound": {"value": "city"}, "to_bound": {"value": "settlement"}},
    )
    response.raise_for_status()
    data = response.json().get("suggestions") or []
    point = data[0].get("data", {}) if data else {}
    if point.get("geo_lat") is None or point.get("geo_lon") is None:
        return None
    return float(point["geo_lat"]), float(point["geo_lon"])


def _haversine(a: tuple[float, float], b: tuple[float, float]) -> int:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return round(6371 * 2 * math.asin(math.sqrt(h)) * 1.28)


async def get_road_distance_km(city_from: str | None, city_to: str | None) -> tuple[int, bool] | None:
    a, b = _clean(city_from), _clean(city_to)
    if not a or not b or a == b or not settings.DADATA_API_KEY:
        return None
    keys = (f"{a}->{b}", f"{b}->{a}")
    if cached := await _cached(keys):
        return cached
    first = second = None
    try:
        async with httpx.AsyncClient(timeout=4.5) as client:
            first, second = await _geocode(client, a), await _geocode(client, b)
            if not first or not second:
                return None
            response = await client.get(f"{OSRM_URL}/{first[1]},{first[0]};{second[1]},{second[0]}?overview=false")
            response.raise_for_status()
            distance = round(response.json()["routes"][0]["distance"] / 1000)
            result = (distance, False)
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        try:
            if not first or not second:
                return None
            result = (_haversine(first, second), True)
        except (UnboundLocalError, TypeError):
            return None
    async with get_db_pool().acquire() as conn:
        await conn.executemany(
            "INSERT INTO route_cache (route_key, distance_km, is_approx) VALUES ($1, $2, $3) ON CONFLICT (route_key) DO UPDATE SET distance_km = EXCLUDED.distance_km, is_approx = EXCLUDED.is_approx, fetched_at = NOW()",
            [(keys[0], *result), (keys[1], *result)],
        )
    return result
