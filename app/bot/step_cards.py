from decimal import Decimal

from bot.ui.screens import fmt_money, vat_tag
from services.calculations.calc_parse import max_carrier_breakeven
from services.parser import ParsedOrder
from services.users import TAX_LABELS


def _details_block(
    route_from: str | None, route_to: str | None, distance_km: int | None,
    distance_approx: bool, weight_t: Decimal | None, cargo_info: str | None,
    body_type: str | None, cargo_date: str | None,
) -> list[str]:
    route = f"📍 **{route_from or 'Откуда'} → {route_to or 'Куда'}**"
    if distance_km:
        route += f" · {'~' if distance_approx else ''}{distance_km} км"
    lines = [route]
    if cargo_info:
        lines.append(f"📦 Груз: {cargo_info}")
    if weight_t is not None and (not cargo_info or f"{weight_t:g} т" not in cargo_info):
        lines.append(f"📦 Тоннаж: {weight_t:g} т")
    if body_type:
        lines.append(f"🚚 Кузов: {body_type}")
    if cargo_date:
        lines.append(f"📅 Погрузка: {cargo_date}")
    return lines


def format_need_client_rate_card(parsed: ParsedOrder, distance_km: int | None, distance_approx: bool) -> str:
    details = _details_block(
        parsed.from_city, parsed.to_city, distance_km, distance_approx,
        parsed.weight_t, parsed.cargo_name, parsed.body_type, parsed.cargo_date,
    )
    details.extend([
        "",
        "В посте вижу груз, но не вижу ставок.",
        "Пришли ставку клиента и перевозчика через `/` "
        "(например: `140 с ндс / 110 ип`) или укажи хотя бы ставку клиента "
        "(`140 с ндс`).",
    ])
    return "\n".join(details)


def format_need_carrier_rate_card(
    parsed: ParsedOrder, tax_mode: str, client_rate: Decimal,
    client_vat: bool | None, distance_km: int | None,
    distance_approx: bool, extra_notes: list[str],
) -> str:
    details = _details_block(
        parsed.from_city, parsed.to_city, distance_km, distance_approx,
        parsed.weight_t, parsed.cargo_name, parsed.body_type, parsed.cargo_date,
    )
    details.extend(["", "💰 Ставки клиента:"] if parsed.client_alt_rate is not None else [
        "", f"💰 Ставка клиента: **{fmt_money(client_rate)} ₽** ({vat_tag(client_vat)})"
    ])
    if parsed.client_alt_rate is not None:
        with_vat = client_rate if client_vat is True else parsed.client_alt_rate
        no_vat = parsed.client_alt_rate if client_vat is True else client_rate
        details.extend([
            f"• с НДС: **{fmt_money(with_vat)} ₽**",
            f"• без НДС: **{fmt_money(no_vat)} ₽**",
            "",
            f"Для режима **{TAX_LABELS[tax_mode]}** беру ставку "
            f"**{vat_tag(client_vat)}**.",
        ])
    no_vat, with_vat = max_carrier_breakeven(tax_mode, client_rate)
    limit = f"**{fmt_money(no_vat)} ₽** (без НДС)"
    if with_vat is not None:
        limit += f" / **{fmt_money(with_vat)} ₽** (с НДС)"
    details.extend(["", f"Перевозчику без убытка до: {limit}"])
    details.extend(["", "💬 **Теперь пришли ставку перевозчика** (например: `110 ип` или `120 с ндс`):"])
    if extra_notes:
        details.extend(f"⚠️ {note}" for note in extra_notes)
    return "\n".join(details)
