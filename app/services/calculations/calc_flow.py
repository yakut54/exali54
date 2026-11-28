from dataclasses import replace
from decimal import Decimal
from bot.ui.keyboards import calc_result_keyboard, keep_result_menu_keyboard
from bot.ui.screens import fmt_money, format_calc_card, vat_tag
from bot.step_cards import format_need_carrier_rate_card, format_need_client_rate_card
from services.calculations.calc_parse import max_carrier_breakeven, parse_carrier_reply, pick_client_offer, solve_rate_for_target_profit
from services.calculations.calculator import calculate_margin, rate_breakdown_by_vat
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
async def build_calc_reply(
    user_id: int, raw_text: str, tax_mode: str, in_dist_mode: bool = False
) -> tuple[str, list[list[dict]]]:
    """Вернуть (текст_ответа, клавиатура) для расчёта рейса."""
    state_row = await get_user_state(user_id)
    carrier_step = bool(state_row and state_row["state"] == "wait_carrier_rate" and state_row["order_id"])
    client_step = bool(state_row and state_row["state"] == "wait_client_rate" and state_row["order_id"])
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
                dist = await get_road_distance_km(order["route_from"], order["route_to"])
                res = calculate_margin(tax_mode, c_rate, carrier_rate, client_vat=c_vat, carrier_vat=bool(carrier_vat), weight_t=w_t, deadhead_km=d_km, route_km=dist[0] if dist else None)
                await complete_order_carrier(order["id"], carrier_rate, carrier_vat, res.net_profit)
                await clear_user_state(user_id)
                card = format_calc_card(order["route_from"], order["route_to"], w_t, res, order["client_vat"], carrier_vat, [], dist[0] if dist else None, dist[1] if dist else False)
                return card, calc_result_keyboard(order["id"])
        await clear_user_state(user_id)
    if client_step:
        order = await get_order(state_row["order_id"], user_id)
        if order:
            raw_text = f"{order['route_from'] or ''} {order['route_to'] or ''} {raw_text}"
    parsed = await parse_order_text(raw_text, in_dist_mode=in_dist_mode)
    if parsed is None:
        if in_dist_mode:
            return "🤔 Укажи два города (например: спб мск или Уссурийск Москва 750 тыс нал)", keep_result_menu_keyboard()
        await log_parse_failure(user_id, raw_text)
        return (
            "🤔 Не смог найти в сообщении маршрут и ставку.\n"
            "Пришли заявку, например: `нск омск 20т 140 с ндс / 100 ип`.",
            keep_result_menu_keyboard(),
        )
    dist = await get_road_distance_km(parsed.from_city, parsed.to_city)
    if in_dist_mode and not (parsed.from_city and parsed.to_city):
        return "🤔 Укажи два города (например: спб мск или Уссурийск Москва 750 тыс нал)", keep_result_menu_keyboard()
    client_rate, client_vat, fork_note = pick_client_offer(parsed, tax_mode)
    if client_step and order:
        parsed = replace(
            parsed,
            weight_t=Decimal(str(order["weight_t"])) if order.get("weight_t") is not None else parsed.weight_t,
            cargo_name=order.get("cargo_info"),
            body_type=order.get("body_type"),
            cargo_date=order.get("cargo_date"),
            deadhead_km=Decimal(str(order["deadhead_km"])) if order.get("deadhead_km") is not None else parsed.deadhead_km,
        )
    carrier_rate = parsed.carrier_rate
    extra_notes = ([fork_note] if fork_note else []) + list(parsed.warnings)
    if parsed.target_profit is not None and ((client_rate is None) != (carrier_rate is None)):
        target = solve_rate_for_target_profit(
            tax_mode, parsed.target_profit, client_rate, carrier_rate,
            bool(client_vat), bool(parsed.carrier_vat), parsed.weight_t,
            parsed.deadhead_km, dist[0] if dist else None,
        )
        if target is None:
            return "⚠️ При этой ставке желаемая прибыль недостижима после налогов.", keep_result_menu_keyboard()
        if client_rate is None:
            client_rate = target
        else:
            carrier_rate = target
        extra_notes.append(f"🎯 Подобрано под желаемую прибыль: {fmt_money(parsed.target_profit)} ₽")
        parsed = replace(parsed, client_rate=client_rate, carrier_rate=carrier_rate)
    if client_rate is None:
        if in_dist_mode and parsed.from_city and parsed.to_city:
            text = (f"📍 {parsed.from_city} → {parsed.to_city}\n"
                    f"🛣 Расстояние по автодорогам: **{'~' if dist[1] else ''}{dist[0]} км**") if dist else f"⚠️ Не удалось определить расстояние между **{parsed.from_city}** и **{parsed.to_city}**."
            return text, keep_result_menu_keyboard()
        if in_dist_mode:
            return "🤔 Укажи два города (например: спб мск или Уссурийск Москва 750 тыс нал)", keep_result_menu_keyboard()
        order_id = await create_order(user_id, raw_text, parsed, None, None, status="need_client_rate")
        await set_user_state(user_id, "wait_client_rate", order_id=order_id)
        return format_need_client_rate_card(parsed, dist[0] if dist else None, dist[1] if dist else False), keep_result_menu_keyboard()
    if parsed.client_rate_type == "per_km" and dist and parsed.distance_km is None:
        client_rate *= dist[0]
    if (in_dist_mode or parsed.calc_mode == "rate_per_km") and (in_dist_mode or parsed.carrier_rate is None):
        breakdown = rate_breakdown_by_vat(client_rate, bool(client_vat), dist[0] if dist else None)
        distance = f"📍 {parsed.from_city} → {parsed.to_city} · {'примерно ' if dist and dist[1] else ''}{dist[0]} км" if dist else "⚠️ Не удалось определить расстояние — ставку за километр не считаю."
        per_km = dist is not None
        return (
            f"{distance}\n"
            f"💰 Сумма: **{fmt_money(client_rate)} ₽** ({'наличные' if parsed.is_cash else vat_tag(client_vat)})\n\n"
            f"Без НДС: **{fmt_money(breakdown['no_vat'])} ₽**" + (f" · **{breakdown['no_vat_per_km']:.1f} ₽/км**" if per_km else "") + "\n"
            f"С НДС 22%: **{fmt_money(breakdown['with_vat'])} ₽**" + (f" · **{breakdown['with_vat_per_km']:.1f} ₽/км**" if per_km else ""),
            keep_result_menu_keyboard(),
        )
    c_vat_eff = bool(client_vat) if client_vat is not None else (tax_mode in ("osno_22", "usn_5_nds"))
    if carrier_rate is None:
        order_id = await create_order(user_id, raw_text, parsed, client_rate, client_vat, status="draft")
        await set_user_state(user_id, "wait_carrier_rate", order_id=order_id)
        return format_need_carrier_rate_card(parsed, tax_mode, client_rate, client_vat, dist[0] if dist else None, dist[1] if dist else False, extra_notes), keep_result_menu_keyboard()
    res = calculate_margin(tax_mode, client_rate, carrier_rate, client_vat=c_vat_eff, carrier_vat=bool(parsed.carrier_vat), weight_t=parsed.weight_t, deadhead_km=parsed.deadhead_km, route_km=dist[0] if dist else None)
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
        "✏️ **Пересчитаем ставку перевозчика**\n"
        f"📍 {order['route_from'] or 'Откуда'} → {order['route_to'] or 'Куда'}\n"
        f"Заказчик: **{fmt_money(client_rate)} ₽**\n"
        f"Потолок в ноль (без НДС): **{fmt_money(max_no_vat)} ₽**\n\n"
        "Пришли новую ставку, например: `105 ип` или `115 с ндс`."
    )
