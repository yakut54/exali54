from decimal import Decimal

from services.calculator import CalcResult
from services.users import TAX_LABELS


def fmt_money(val: Decimal) -> str:
    return f"{val:,.2f}".replace(",", " ").replace(".00", "")


def vat_tag(vat: bool | None) -> str:
    if vat is True:
        return "с НДС"
    if vat is False:
        return "без НДС"
    return "НДС не указан"


def screen_text(screen: str, tax_mode: str = "osno_22") -> str:
    tax_name = TAX_LABELS.get(tax_mode, tax_mode)
    if screen == "home":
        return (
            "**🚚 Ехали! • Ассистент логиста**\n"
            f"Налог: **{tax_name}**\n\n"
            "Пришли параметры рейса (или перешли пост из чата) либо выбери инструмент:"
        )
    if screen == "tax":
        return f"**⚙️ Система налогообложения**\nСейчас: **{tax_name}**"
    if screen == "calc":
        return (
            "**🧮 Стоп-цена и маржа**\n"
            "Напиши рейс одной строкой или перешли пост с грузом:\n"
            "`нск омск 20т 140 с ндс / 100 ип подача 40`"
        )
    if screen == "inn":
        return "**🛡 Проверка ИНН**\nОтправь `10` или `12` цифр ИНН контрагента:"
    return "**📄 Сбор ТТН**\nСоздание ссылки для водителя (скоро)"


def format_calc_card(
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
        f"Заказчик: **{fmt_money(res.client_rate)} ₽** ({vat_tag(client_vat)})",
        f"Перевозчик: **{fmt_money(res.carrier_rate)} ₽** ({vat_tag(carrier_vat)})",
        f"Налоги (НДС {fmt_money(res.vat_to_pay)} + налог {fmt_money(res.income_tax)}): **{fmt_money(res.total_taxes)} ₽**",
        "",
        f"{profit_icon} Чистая прибыль: **{fmt_money(res.net_profit)} ₽** (**{res.margin_pct}%**)",
        f"🛑 Стоп-цена для клиента: **{fmt_money(res.stop_price)} ₽**",
    ]
    if res.carrier_with_vat_eq is not None:
        lines.append(f"⚖️ Эквивалент ставки перевозчика с НДС: **{fmt_money(res.carrier_with_vat_eq)} ₽**")
    if res.platon_hint is not None:
        lines.append(f"🛣 Платон за подачу: ~**{fmt_money(res.platon_hint)} ₽**")

    notes = ([res.warning] if res.warning else []) + extra_notes
    if carrier_vat is None and res.tax_mode == "osno_22":
        notes.append("НДС перевозчика не указан — расчёт выполнен как БЕЗ НДС.")
    if notes:
        lines.append("")
        lines.extend(f"⚠️ {n}" for n in notes)
    return "\n".join(lines)
