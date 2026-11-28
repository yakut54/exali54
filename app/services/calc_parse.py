import re
from decimal import Decimal, InvalidOperation

from bot.screens import fmt_money, vat_tag
from services.parser import ParsedOrder


def max_carrier_breakeven(tax_mode: str, client_rate: Decimal) -> tuple[Decimal, Decimal | None]:
    if tax_mode == "osno_22":
        return client_rate * Decimal("100") / Decimal("122"), client_rate
    if tax_mode == "usn_5_nds":
        return (client_rate * Decimal("100") / Decimal("105")) * Decimal("0.94"), None
    if tax_mode == "usn_6":
        return client_rate * Decimal("0.94"), None
    if tax_mode == "usn_6_agent":
        return client_rate, None
    if tax_mode == "usn_15":
        return client_rate * Decimal("0.99"), None
    return Decimal("0"), None


def pick_client_offer(parsed: ParsedOrder, tax_mode: str) -> tuple[Decimal, bool | None, str | None]:
    if parsed.client_alt_rate is None:
        return parsed.client_rate, parsed.client_vat, None
    wants_vat = tax_mode in ("osno_22", "usn_5_nds")
    if wants_vat and parsed.client_alt_vat is True and parsed.client_vat is not True:
        return parsed.client_alt_rate, True, f"Взял ставку с НДС: {fmt_money(parsed.client_alt_rate)} ₽"
    if not wants_vat and parsed.client_alt_vat is False and parsed.client_vat is not False:
        return parsed.client_alt_rate, False, f"Взял ставку без НДС: {fmt_money(parsed.client_alt_rate)} ₽"
    note = f"Вторая ставка: {fmt_money(parsed.client_alt_rate)} ₽ ({vat_tag(parsed.client_alt_vat)})"
    return parsed.client_rate, parsed.client_vat, note


def format_cargo_post(order: dict, distance_km: int | None = None) -> str:
    route = f"🚛 **Груз: {order['route_from'] or 'Откуда'} → {order['route_to'] or 'Куда'}**"
    if distance_km:
        route += f" ({distance_km} км)"
    lines = [route]
    if order.get("weight_t"):
        lines.append(f"📦 Тоннаж: {Decimal(str(order['weight_t'])):g} т")
    if order.get("carrier_rate"):
        rate = Decimal(str(order["carrier_rate"]))
        lines.append(f"💰 Ставка перевозчику: **{fmt_money(rate)} ₽** ({vat_tag(order.get('carrier_vat'))})")
    lines.append("📩 Подробности и погрузка — в ЛС")
    return "\n".join(lines)


def parse_carrier_reply(text: str) -> tuple[Decimal | None, bool | None]:
    if "/" in text or "-" in text or len(text) > 35:
        return None, None
    cleaned = text.lower().replace(" ", "").replace("\u00a0", "")
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)(?:к|тыс|тр|р|руб)?[а-яa-z/+\s]*", cleaned)
    if not m:
        return None, None
    try:
        raw = Decimal(m.group(1).replace(",", "."))
    except InvalidOperation:
        return None, None
    if raw <= 0:
        return None, None
    rate = raw * Decimal("1000") if raw < Decimal("1000") else raw
    low = text.lower()
    if any(k in low for k in ("с ндс", "+ндс", "эндээс", "осно")):
        return rate, True
    if any(k in low for k in ("без ндс", "ип", "усн", "нал", "карт", "б/н")):
        return rate, False
    return rate, None
