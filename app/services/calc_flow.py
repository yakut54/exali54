import re
from decimal import Decimal, InvalidOperation

from bot.client import MaxClient
from bot.keyboards import back_to_home_keyboard
from services.calculator import CalcResult, calculate_margin
from services.orders import (
    clear_user_state,
    complete_order_carrier,
    create_order,
    get_order,
    get_user_state,
    set_user_state,
)
from services.parser import ParsedOrder, parse_order_text
from services.users import TAX_LABELS


def _fmt_money(val: Decimal) -> str:
    return f"{val:,.2f}".replace(",", " ").replace(".00", "")


def _vat_tag(vat: bool | None) -> str:
    if vat is True:
        return "с НДС"
    if vat is False:
        return "без НДС"
    return "НДС не указан"


def _max_carrier_breakeven(tax_mode: str, client_rate: Decimal, client_vat: bool) -> tuple[Decimal, Decimal | None]:
    if tax_mode == "osno_22":
        return client_rate * Decimal("100") / Decimal("122"), client_rate
    if tax_mode == "usn_5_nds":
        rev_net = client_rate * Decimal("100") / Decimal("105")
        return rev_net * Decimal("0.94"), None
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
        note = f"Из вилки выбрана ставка с НДС ({_fmt_money(parsed.client_alt_rate)} ₽)"
        return parsed.client_alt_rate, True, note
    if not wants_vat and parsed.client_alt_vat is False and parsed.client_vat is not False:
        note = f"Из вилки выбрана ставка без НДС ({_fmt_money(parsed.client_alt_rate)} ₽)"
        return parsed.client_alt_rate, False, note

    note = f"Вторая ставка в вилке: {_fmt_money(parsed.client_alt_rate)} ₽ ({_vat_tag(parsed.client_alt_vat)})"
    return parsed.client_rate, parsed.client_vat, note


def _format_calc_card(
    route_from: str | None,
    route_to: str | None,
    weight_t: Decimal | None,
    res: CalcResult,
    client_vat: bool | None,
    carrier_vat: bool | None,
    extra_notes: list[str],
) -> str:
    title = f"**📍 {route_from or 'Откуда'} → {route_to or 'Куда'}**"
    if weight_t is not None:
        title += f" ({weight_t:g} т)"

    profit_icon = "🟢" if res.net_profit > 0 else "🔴"
    lines = [
        title,
        f"Режим: **{TAX_LABELS.get(res.tax_mode, res.tax_mode)}**",
        "",
        f"Заказчик: **{_fmt_money(res.client_rate)} ₽** ({_vat_tag(client_vat)})",
        f"Перевозчик: **{_fmt_money(res.carrier_rate)} ₽** ({_vat_tag(carrier_vat)})",
        f"Налоги (НДС {_fmt_money(res.vat_to_pay)} + налог {_fmt_money(res.income_tax)}): **{_fmt_money(res.total_taxes)} ₽**",
        "",
        f"{profit_icon} Чистая прибыль: **{_fmt_money(res.net_profit)} ₽** (**{res.margin_pct}%**)",
        f"🛑 Стоп-цена для клиента: **{_fmt_money(res.stop_price)} ₽**",
    ]
    if res.carrier_with_vat_eq is not None:
        lines.append(f"⚖️ Эквивалент ставки перевозчика с НДС: **{_fmt_money(res.carrier_with_vat_eq)} ₽**")
    if res.platon_hint is not None:
        lines.append(f"🛣 Платон за подачу: ~**{_fmt_money(res.platon_hint)} ₽**")

    notes = ([res.warning] if res.warning else []) + extra_notes
    if carrier_vat is None and res.tax_mode == "osno_22":
        notes.append("НДС перевозчика не указан — расчёт выполнен как БЕЗ НДС.")
    if notes:
        lines.append("")
        lines.extend(f"⚠️ {n}" for n in notes)

    return "\n".join(lines)


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

    vat: bool | None = None
    low = text.lower()
    if any(k in low for k in ("с ндс", "+ндс", "эндээс", "осно")):
        vat = True
    elif any(k in low for k in ("без ндс", "ип", "усн", "нал", "карт", "б/н")):
        vat = False
    return rate, vat


async def handle_calc_text(chat_id: int, user_id: int, raw_text: str, tax_mode: str, max_client: MaxClient) -> None:
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
                card = _format_calc_card(
                    order["route_from"], order["route_to"], None, res, order["client_vat"], carrier_vat, []
                )
                await max_client.send_message(chat_id, card, buttons=back_to_home_keyboard())
                return
        await clear_user_state(user_id)

    parsed = await parse_order_text(raw_text)
    if parsed is None:
        msg = (
            "🤔 Не вижу ставок в сообщении.\n"
            "Пришли рейс с ценами (например: `нск омск 20т 140 с ндс / 100 ип`) "
            "или перешли пост, где указана ставка заказчика."
        )
        await max_client.send_message(chat_id, msg, buttons=back_to_home_keyboard())
        return

    client_rate, client_vat, fork_note = _pick_client_offer(parsed, tax_mode)
    extra_notes = ([fork_note] if fork_note else []) + list(parsed.warnings)
    c_vat_effective = bool(client_vat) if client_vat is not None else (tax_mode in ("osno_22", "usn_5_nds"))

    if parsed.carrier_rate is None:
        order_id = await create_order(user_id, raw_text, parsed, client_rate, client_vat, status="draft")
        await set_user_state(user_id, "wait_carrier_rate", order_id=order_id)

        if client_vat is False and tax_mode == "osno_22":
            extra_notes.insert(0, "Вы на ОСНО: НДС 22% выделен из ставки клиента, уточните договор.")
        elif client_vat is False and tax_mode == "usn_5_nds":
            extra_notes.insert(0, "УСН + НДС 5%: в ставку клиента заложен НДС 5%.")

        max_no_vat, max_with_vat = _max_carrier_breakeven(tax_mode, client_rate, c_vat_effective)
        route = f"**📍 {parsed.from_city or 'Откуда'} → {parsed.to_city or 'Куда'}**"
        if parsed.weight_t is not None:
            route += f" ({parsed.weight_t:g} т)"

        lines = [
            route,
            f"Заказчик: **{_fmt_money(client_rate)} ₽** ({_vat_tag(client_vat)})",
            f"Потолок в ноль (без НДС): **{_fmt_money(max_no_vat)} ₽**",
        ]
        if max_with_vat is not None:
            lines.append(f"Потолок в ноль (с НДС): **{_fmt_money(max_with_vat)} ₽**")
        lines.extend([
            "",
            "💬 **За сколько забирает перевозчик?**\nНапиши ставку (например: `110 ип` или `120 с ндс`):",
        ])
        if extra_notes:
            lines.append("")
            lines.extend(f"⚠️ {n}" for n in extra_notes)
        await max_client.send_message(chat_id, "\n".join(lines), buttons=back_to_home_keyboard())
        return

    res = calculate_margin(
        tax_mode,
        client_rate,
        parsed.carrier_rate,
        client_vat=c_vat_effective,
        carrier_vat=bool(parsed.carrier_vat),
        weight_t=parsed.weight_t,
        deadhead_km=parsed.deadhead_km,
    )
    await create_order(user_id, raw_text, parsed, client_rate, client_vat, margin=res.net_profit, status="calculated")
    card = _format_calc_card(
        parsed.from_city, parsed.to_city, parsed.weight_t, res, client_vat, parsed.carrier_vat, extra_notes
    )
    await max_client.send_message(chat_id, card, buttons=back_to_home_keyboard())
