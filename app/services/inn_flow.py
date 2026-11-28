import re

import httpx

from bot.keyboards import keep_result_menu_keyboard
from bot.screens import format_inn_card
from config import settings
from services.antifraud import check_inn
from services.users import check_and_inc_inn_limit

_INN_LENGTHS = (10, 12)
_DIGITS_ONLY = re.compile(r"[\d\s]+")


def extract_inn(raw_text: str) -> str:
    return re.sub(r"\D", "", raw_text or "")


def is_inn_text(raw_text: str) -> bool:
    text = (raw_text or "").strip()
    return bool(_DIGITS_ONLY.fullmatch(text)) and len(extract_inn(text)) in _INN_LENGTHS


def is_order_text(raw_text: str) -> bool:
    text = (raw_text or "").strip()
    return "/" in text or (len(text) > 25 and any(ch.isalpha() for ch in text))


async def build_inn_reply(user_id: int, raw_text: str) -> tuple[str, list[list[dict]]]:
    if not await check_and_inc_inn_limit(user_id):
        return (f"⚠️ Бета-тест: достигнут суточный лимит ({settings.DAILY_INN_LIMIT} проверок ИНН в день). "
                "Счётчик обновится завтра.", keep_result_menu_keyboard())
    digits = extract_inn(raw_text)
    try:
        report = await check_inn(digits)
    except ValueError as exc:
        return str(exc), keep_result_menu_keyboard()
    except RuntimeError:
        return ("⚠️ Сервис проверки ИНН временно недоступен (не задан ключ API).",
                keep_result_menu_keyboard())
    except httpx.HTTPError:
        return ("⚠️ Не удалось связаться с реестром ФНС/DaData. Попробуй через минуту.",
                keep_result_menu_keyboard())
    if report is None:
        return (f"🔍 Организация или ИП с ИНН `{digits}` не найдены в ЕГРЮЛ/ЕГРИП.",
                keep_result_menu_keyboard())
    return format_inn_card(report), keep_result_menu_keyboard()
