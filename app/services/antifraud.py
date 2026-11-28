import json
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from config import settings
from db import get_db_pool

_WEIGHTS_10 = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_WEIGHTS_11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_WEIGHTS_12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def _check_digit(digits: str, weights: tuple[int, ...]) -> int:
    return sum(int(d) * w for d, w in zip(digits, weights)) % 11 % 10


def validate_inn(inn: str) -> bool:
    value = (inn or "").strip()
    if len(value) not in (10, 12) or not (value.isdigit() and value.isascii()):
        return False
    if len(value) == 10:
        return _check_digit(value[:9], _WEIGHTS_10) == int(value[9])
    return (_check_digit(value[:10], _WEIGHTS_11) == int(value[10])
            and _check_digit(value[:11], _WEIGHTS_12) == int(value[11]))


@dataclass(frozen=True)
class InnReport:
    inn: str
    name: str
    status: str
    reg_date: str | None
    address: str | None
    manager: str | None
    okved: str | None
    from_cache: bool


def _as_dict(payload) -> dict:
    return json.loads(payload) if isinstance(payload, str) else dict(payload)


def _build_report(inn: str, suggestion: dict, from_cache: bool) -> InnReport:
    data = suggestion.get("data") or {}
    names = data.get("name") or {}
    state = data.get("state") or {}
    management = data.get("management") or {}
    manager = ", ".join(p for p in (management.get("name"), management.get("post")) if p) or None
    reg_ms = data.get("registration_date")
    reg_date = (
        datetime.fromtimestamp(reg_ms / 1000, tz=timezone.utc).strftime("%d.%m.%Y")
        if isinstance(reg_ms, (int, float)) else None
    )
    name = (names.get("short_with_opf") or names.get("full_with_opf")
            or names.get("full") or suggestion.get("value") or "")
    return InnReport(
        inn=inn,
        name=name,
        status=state.get("status") or "",
        reg_date=reg_date,
        address=(data.get("address") or {}).get("value") or None,
        manager=manager,
        okved=data.get("okved") or None,
        from_cache=from_cache,
    )


async def check_inn(inn: str) -> InnReport | None:
    value = (inn or "").strip()
    if not validate_inn(value):
        raise ValueError("Некорректная контрольная сумма ИНН")

    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT payload FROM inn_cache WHERE inn = $1 "
            "AND fetched_at > NOW() - INTERVAL '24 hours'",
            value,
        )
    if row is not None:
        return _build_report(value, _as_dict(row["payload"]), True)

    if not settings.DADATA_API_KEY:
        raise RuntimeError("DADATA_API_KEY не настроен")

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            settings.DADATA_INN_URL,
            headers={"Authorization": f"Token {settings.DADATA_API_KEY}"},
            json={"query": value, "branch_type": "MAIN"},
        )
        response.raise_for_status()
        suggestions = (response.json() or {}).get("suggestions") or []
    if not suggestions:
        return None
    suggestion = suggestions[0]

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO inn_cache (inn, payload, fetched_at) VALUES ($1, $2, NOW()) "
            "ON CONFLICT (inn) DO UPDATE "
            "SET payload = EXCLUDED.payload, fetched_at = NOW()",
            value,
            json.dumps(suggestion, ensure_ascii=False),
        )
    return _build_report(value, suggestion, False)
