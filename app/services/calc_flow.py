from decimal import Decimal

from bot.keyboards import calc_result_keyboard, keep_result_menu_keyboard
from bot.screens import fmt_money, format_calc_card, vat_tag
from services.calc_parse import max_carrier_breakeven, parse_carrier_reply, pick_client_offer
from services.calculator import calculate_margin
from services.calculator import rate_breakdown_by_vat
from services.distance import get_road_distance_km
from services.orders import (
    clear_user_state,
    complete_order_carrier,
    create_order,
    get_order,
    get_user_state,
    set_user_state,
)
from services.parser import parse_order_text
from services.users import is_calc_limit_exceeded, log_parse_failure


async def build_calc_reply(user_id: int, raw_text: str, tax_mode: str) -> tuple[str, list[list[dict]]]:
    """Вернуть (текст_ответа, клавиатура) для расчёта рейса."""
    state_row = await get_user_state(user_id)
    carrier_step = bool(state_row and state_row["state"] == "wait_carrier_rate" and state_row["order_id"])
    if not carrier_step and (limit_msg := await is_calc_limit_exceeded(user_id)):
        return limit_msg, keep_result_menu_keyboard()
    if carrier_step:
        carrier_rate, carrier_vat = parse_carrier_reply(raw_text)
        if carrier_rate is not None:
            order = await get_order(state_row["order_id"], user_id)
            if order and order["client_rate"]:
                c_rate = Decimal(str(order["client_rate"]))
                c_vat = bool(order["client_vat"]) if order["client_vat"] is not None else (tax_mode in ("osno_22", "usn_5_nds"))
                w_t = Decimal(str(order["weight_t"])) if order.get("weight_t") is not None else None
                d_km = Decimal(str(order["deadhead_km"])) if order.get("deadhead_km") is not None else None
                res = calculate_margin(tax_mode, c_rate, carrier_rate, client_vat=c_vat, carrier_vat=bool(carrier_vat), weight_t=w_t, deadhead_km=d_km)
                await complete_order_carrier(order["id"], carrier_rate, carrier_vat, res.net_profit)
                await clear_user_state(user_id)
                dist = await get_road_distance_km(order["route_from"], order["route_to"])
                card = format_calc_card(order["route_from"], order["route_to"], w_t, res, order["client_vat"], carrier_vat, [], dist[0] if dist else None, dist[1] if dist else False)
                return card, calc_result_keyboard(order["id"])
        await clear_user_state(user_id)

    parsed = await parse_order_text(raw_text)
    if parsed is None:
        await log_parse_failure(user_id, raw_text)
        return (
            "🤔 Не вижу ставок в сообщении.\n"
            "Пришли рейс с ценами (например: `нск омск 20т 140 с ндс / 100 ип`) или перешли пост со ставкой заказчика.",
            keep_result_menu_keyboard(),
        )

    client_rate, client_vat, fork_note = pick_client_offer(parsed, tax_mode)
    dist = await get_road_distance_km(parsed.from_city, parsed.to_city)
    if parsed.client_rate_type == "per_km" and dist and parsed.distance_km is None:
        client_rate *= dist[0]
    if parsed.calc_mode == "rate_per_km" and parsed.carrier_rate is None:
        breakdown = rate_breakdown_by_vat(client_rate, bool(client_vat), dist[0] if dist else None)
        distance = f"📍 **{parsed.from_city} → {parsed.to_city}** · {'~' if dist and dist[1] else ''}{dist[0]} км" if dist else "⚠️ Расстояние не удалось определить, ₽/км не рассчитан."
        per_km = dist is not None
        return (
            f"{distance}\n"
            f"💰 Сумма: **{fmt_money(client_rate)} ₽** ({'наличные' if parsed.is_cash else vat_tag(client_vat)})\n\n"
            f"Без НДС: **{fmt_money(breakdown['no_vat'])} ₽**" + (f" · **{breakdown['no_vat_per_km']:.1f} ₽/км**" if per_km else "") + "\n"
            f"С НДС 22%: **{fmt_money(breakdown['with_vat'])} ₽**" + (f" · **{breakdown['with_vat_per_km']:.1f} ₽/км**" if per_km else ""),
            keep_result_menu_keyboard(),
        )
    extra_notes = ([fork_note] if fork_note else []) + list(parsed.warnings)
    c_vat_eff = bool(client_vat) if client_vat is not None else (tax_mode in ("osno_22", "usn_5_nds"))

    if parsed.carrier_rate is None:
        order_id = await create_order(user_id, raw_text, parsed, client_rate, client_vat, status="draft")
        await set_user_state(user_id, "wait_carrier_rate", order_id=order_id)
        if client_vat is False and tax_mode == "osno_22":
            extra_notes.insert(0, "Вы на ОСНО: НДС 22% выделен из ставки клиента, уточните договор.")
        elif client_vat is False and tax_mode == "usn_5_nds":
            extra_notes.insert(0, "УСН + НДС 5%: в ставку клиента заложен НДС 5%.")

        max_no_vat, max_with_vat = max_carrier_breakeven(tax_mode, client_rate)
        route = f"**📍 {parsed.from_city or 'Откуда'} → {parsed.to_city or 'Куда'}**" + (f" ({parsed.weight_t:g} т)" if parsed.weight_t else "")
        lines = [route, f"Заказчик: **{fmt_money(client_rate)} ₽** ({vat_tag(client_vat)})", f"Потолок в ноль (без НДС): **{fmt_money(max_no_vat)} ₽**"]
        if max_with_vat is not None:
            lines.append(f"Потолок в ноль (с НДС): **{fmt_money(max_with_vat)} ₽**")
        lines.extend(["", "💬 **За сколько забирает перевозчик?**\nНапиши ставку (например: `110 ип` или `120 с ндс`):"])
        if extra_notes:
            lines.extend(["", *(f"⚠️ {n}" for n in extra_notes)])
        return "\n".join(lines), keep_result_menu_keyboard()

    res = calculate_margin(tax_mode, client_rate, parsed.carrier_rate, client_vat=c_vat_eff, carrier_vat=bool(parsed.carrier_vat), weight_t=parsed.weight_t, deadhead_km=parsed.deadhead_km)
    order_id = await create_order(user_id, raw_text, parsed, client_rate, client_vat, margin=res.net_profit, status="calculated")
    card = format_calc_card(parsed.from_city, parsed.to_city, parsed.weight_t, res, client_vat, parsed.carrier_vat, extra_notes, dist[0] if dist else None, dist[1] if dist else False)
    return card, calc_result_keyboard(order_id)


async def start_recalc_carrier(user_id: int, order_id: int, tax_mode: str) -> str | None:
    """Открыть повторный торг: запомнить рейс и вернуть подсказку со ставками."""
    order = await get_order(order_id, user_id)
    if order is None or order["client_rate"] is None:
        return None
    await set_user_state(user_id, "wait_carrier_rate", order_id=order_id)
    client_rate = Decimal(str(order["client_rate"]))
    max_no_vat, _ = max_carrier_breakeven(tax_mode, client_rate)
    return (
        "✏️ **Пересчёт ставки водителя**\n"
        f"📍 {order['route_from'] or 'Откуда'} → {order['route_to'] or 'Куда'}\n"
        f"Заказчик: **{fmt_money(client_rate)} ₽**\n"
        f"Потолок в ноль (без НДС): **{fmt_money(max_no_vat)} ₽**\n\n"
        "Напиши новую ставку перевозчика (например: `105 ип` или `115 с ндс`):"
    )
