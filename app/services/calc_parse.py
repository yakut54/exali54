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
    cargo = order.get("cargo_info")
    body = order.get("body_type")
    if cargo or body:
        lines.append(f"📦 Груз и кузов: {' · '.join(x for x in (cargo, body) if x)}")
    elif order.get("weight_t"):
        lines.append(f"📦 Тоннаж: {Decimal(str(order['weight_t'])):g} т")
    if order.get("cargo_date"):
        lines.append(f"📅 Погрузка: {order['cargo_date']}")
    if order.get("carrier_rate"):
        rate = Decimal(str(order["carrier_rate"]))
        lines.append(f"💰 Ставка перевозчику: **{fmt_money(rate)} ₽** ({vat_tag(order.get('carrier_vat'))})")
    lines.append("📩 Подробности и погрузка — в ЛС")
    return "\n".join(lines)


def solve_rate_for_target_profit(
    tax_mode: str, target_profit: Decimal, client_rate: Decimal | None,
    carrier_rate: Decimal | None, client_vat: bool, carrier_vat: bool,
    weight_t: Decimal | None = None, deadhead_km: Decimal | None = None,
    route_km: int | None = None,
) -> Decimal | None:
    from services.calculator import calculate_margin
    if (client_rate is None) == (carrier_rate is None):
        return None
    if client_rate is not None:
        if calculate_margin(tax_mode, client_rate, Decimal("0"), client_vat, carrier_vat, weight_t, deadhead_km, route_km).net_profit < target_profit:
            return None
        lo, hi = Decimal("0"), client_rate
        for _ in range(30):
            mid = ((lo + hi) / 2).quantize(Decimal("1"))
            if calculate_margin(tax_mode, client_rate, mid, client_vat, carrier_vat, weight_t, deadhead_km, route_km).net_profit >= target_profit:
                lo = mid
            else:
                hi = mid
        return lo
    lo, hi = carrier_rate, carrier_rate * 5 + Decimal("500000")
    for _ in range(30):
        mid = ((lo + hi) / 2).quantize(Decimal("1"))
        if calculate_margin(tax_mode, mid, carrier_rate, client_vat, carrier_vat, weight_t, deadhead_km, route_km).net_profit >= target_profit:
            hi = mid
        else:
            lo = mid
    return hi if calculate_margin(tax_mode, hi, carrier_rate, client_vat, carrier_vat, weight_t, deadhead_km, route_km).net_profit >= target_profit else None


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
