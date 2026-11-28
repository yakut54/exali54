import re
from decimal import Decimal, InvalidOperation

from bot.keyboards import keep_result_menu_keyboard
from bot.screens import fmt_money, format_calc_card, vat_tag
from services.calculator import calculate_margin
from services.orders import (
    clear_user_state,
    complete_order_carrier,
    create_order,
    get_order,
    get_user_state,
    set_user_state,
)
from services.parser import ParsedOrder, parse_order_text


def _max_carrier_breakeven(tax_mode: str, client_rate: Decimal) -> tuple[Decimal, Decimal | None]:
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


def _pick_client_offer(parsed: ParsedOrder, tax_mode: str) -> tuple[Decimal, bool | None, str | None]:
    if parsed.client_alt_rate is None:
        return parsed.client_rate, parsed.client_vat, None
    wants_vat = tax_mode in ("osno_22", "usn_5_nds")
    if wants_vat and parsed.client_alt_vat is True and parsed.client_vat is not True:
        return parsed.client_alt_rate, True, f"Из вилки выбрана ставка с НДС ({fmt_money(parsed.client_alt_rate)} ₽)"
    if not wants_vat and parsed.client_alt_vat is False and parsed.client_vat is not False:
        return parsed.client_alt_rate, False, f"Из вилки выбрана ставка без НДС ({fmt_money(parsed.client_alt_rate)} ₽)"
    note = f"Вторая ставка в вилке: {fmt_money(parsed.client_alt_rate)} ₽ ({vat_tag(parsed.client_alt_vat)})"
    return parsed.client_rate, parsed.client_vat, note


def _parse_carrier_reply(text: str) -> tuple[Decimal | None, bool | None]:
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


async def build_calc_reply(user_id: int, raw_text: str, tax_mode: str) -> tuple[str, list[list[dict]]]:
    """Вернуть (текст_ответа, клавиатура) для расчёта рейса."""
    state_row = await get_user_state(user_id)
    if state_row and state_row["state"] == "wait_carrier_rate" and state_row["order_id"]:
        carrier_rate, carrier_vat = _parse_carrier_reply(raw_text)
        if carrier_rate is not None:
            order = await get_order(state_row["order_id"], user_id)
            if order and order["client_rate"]:
                c_rate = Decimal(str(order["client_rate"]))
                c_vat = bool(order["client_vat"]) if order["client_vat"] is not None else (tax_mode in ("osno_22", "usn_5_nds"))
                res = calculate_margin(tax_mode, c_rate, carrier_rate, client_vat=c_vat, carrier_vat=bool(carrier_vat))
                await complete_order_carrier(order["id"], carrier_rate, carrier_vat, res.net_profit)
                await clear_user_state(user_id)
                card = format_calc_card(order["route_from"], order["route_to"], None, res, order["client_vat"], carrier_vat, [])
                return card, keep_result_menu_keyboard()
        await clear_user_state(user_id)

    parsed = await parse_order_text(raw_text)
    if parsed is None:
        return (
            "🤔 Не вижу ставок в сообщении.\n"
            "Пришли рейс с ценами (например: `нск омск 20т 140 с ндс / 100 ип`) или перешли пост со ставкой заказчика.",
            keep_result_menu_keyboard(),
        )

    client_rate, client_vat, fork_note = _pick_client_offer(parsed, tax_mode)
    extra_notes = ([fork_note] if fork_note else []) + list(parsed.warnings)
    c_vat_eff = bool(client_vat) if client_vat is not None else (tax_mode in ("osno_22", "usn_5_nds"))

    if parsed.carrier_rate is None:
        order_id = await create_order(user_id, raw_text, parsed, client_rate, client_vat, status="draft")
        await set_user_state(user_id, "wait_carrier_rate", order_id=order_id)
        if client_vat is False and tax_mode == "osno_22":
            extra_notes.insert(0, "Вы на ОСНО: НДС 22% выделен из ставки клиента, уточните договор.")
        elif client_vat is False and tax_mode == "usn_5_nds":
            extra_notes.insert(0, "УСН + НДС 5%: в ставку клиента заложен НДС 5%.")

        max_no_vat, max_with_vat = _max_carrier_breakeven(tax_mode, client_rate)
        route = f"**📍 {parsed.from_city or 'Откуда'} → {parsed.to_city or 'Куда'}**" + (f" ({parsed.weight_t:g} т)" if parsed.weight_t else "")
        lines = [route, f"Заказчик: **{fmt_money(client_rate)} ₽** ({vat_tag(client_vat)})", f"Потолок в ноль (без НДС): **{fmt_money(max_no_vat)} ₽**"]
        if max_with_vat is not None:
            lines.append(f"Потолок в ноль (с НДС): **{fmt_money(max_with_vat)} ₽**")
        lines.extend(["", "💬 **За сколько забирает перевозчик?**\nНапиши ставку (например: `110 ип` или `120 с ндс`):"])
        if extra_notes:
            lines.extend(["", *(f"⚠️ {n}" for n in extra_notes)])
        return "\n".join(lines), keep_result_menu_keyboard()

    res = calculate_margin(tax_mode, client_rate, parsed.carrier_rate, client_vat=c_vat_eff, carrier_vat=bool(parsed.carrier_vat), weight_t=parsed.weight_t, deadhead_km=parsed.deadhead_km)
    await create_order(user_id, raw_text, parsed, client_rate, client_vat, margin=res.net_profit, status="calculated")
    card = format_calc_card(parsed.from_city, parsed.to_city, parsed.weight_t, res, client_vat, parsed.carrier_vat, extra_notes)
    return card, keep_result_menu_keyboard()
