from decimal import Decimal

from services.inn.antifraud import InnReport
from services.calculations.calculator import CalcResult
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
            f"Налоговый режим: **{tax_name}**\n\n"
            "Выбери нужный инструмент или пришли заявку прямо в чат."
        )
    if screen == "tax":
        return f"**⚙️ Налоговый режим**\nСейчас выбран: **{tax_name}**"
    if screen == "calc":
        return (
            "**🧮 Стоп-цена и маржа**\n"
            "Пришли заявку одной строкой или перешли пост с грузом:\n"
            "`нск омск 20т 140 с ндс / 100 ип подача 40`"
        )
    if screen == "dist":
        return (
            "**🛣 Расстояние и ₽/км**\n"
            "Укажи маршрут:\n"
            "• `Уссурийск — Москва` — покажу расстояние по трассе\n"
            "• `Уссурийск — Москва 750 тыс наличными` — "
            "покажу эквивалент в ₽/км с НДС и без НДС"
        )
    if screen == "inn":
        return "**🛡 Проверка ИНН**\nПришли 10 или 12 цифр ИНН контрагента."
    return "**📄 Сбор ТТН**\nСоздай ссылку для водителя и получи готовый PDF."


def format_calc_card(
    route_from: str | None,
    route_to: str | None,
    weight_t: Decimal | None,
    res: CalcResult,
    client_vat: bool | None,
    carrier_vat: bool | None,
    extra_notes: list[str],
    distance_km: int | None = None,
    distance_approx: bool = False,
) -> str:
    title = f"**📍 {route_from or 'Откуда'} → {route_to or 'Куда'}**"
    if weight_t is not None:
        title += f" ({weight_t:g} т)"
    if distance_km:
        title += f" · {'~' if distance_approx else ''}{distance_km} км"

    profit_icon = "🟢" if res.net_profit > 0 else "🔴"
    lines = [
        title,
        f"Налоговый режим: **{TAX_LABELS.get(res.tax_mode, res.tax_mode)}**",
        "",
        f"Ставка клиента: **{fmt_money(res.client_rate)} ₽** ({vat_tag(client_vat)})",
        f"Ставка перевозчика: **{fmt_money(res.carrier_rate)} ₽** ({vat_tag(carrier_vat)})",
        f"Налоги: **{fmt_money(res.total_taxes)} ₽** (НДС {fmt_money(res.vat_to_pay)} + налог {fmt_money(res.income_tax)})",
        "",
        f"{profit_icon} Прибыль: **{fmt_money(res.net_profit)} ₽** (**{res.margin_pct}%**)",
        f"🛑 Минимальная ставка клиента: **{fmt_money(res.stop_price)} ₽**",
    ]
    if res.carrier_with_vat_eq is not None:
        lines.append(f"⚖️ Ставка перевозчика с НДС: **{fmt_money(res.carrier_with_vat_eq)} ₽**")
    if res.platon_hint is not None:
        lines.append(f"🛣 Платон (от 12 т, ~75% фед. трасс): ~**{fmt_money(res.platon_hint)} ₽**")

    notes = ([res.warning] if res.warning else []) + extra_notes
    if carrier_vat is None and res.tax_mode == "osno_22":
        notes.append("НДС перевозчика не указан — считаю ставку без НДС.")
    if notes:
        lines.append("")
        lines.extend(f"⚠️ {n}" for n in notes)
    return "\n".join(lines)


INN_STATUS_LABELS: dict[str, str] = {
    "ACTIVE": "🟢 Действующая",
    "LIQUIDATING": "🟡 В стадии ликвидации",
    "LIQUIDATED": "🔴 Ликвидирована",
    "BANKRUPT": "🔴 Банкротство",
    "REORGANIZING": "🟡 Реорганизация",
}


def format_inn_card(report: InnReport) -> str:
    status = INN_STATUS_LABELS.get(report.status, report.status or "нет данных")
    lines = [
        f"**{report.name or 'Наименование не указано'}**",
        f"ИНН: `{report.inn}`",
        f"Статус: {status}",
    ]
    if report.reg_date:
        lines.append(f"Дата регистрации: {report.reg_date}")
    if report.manager:
        lines.append(f"Руководитель: {report.manager}")
    if report.okved:
        lines.append(f"ОКВЭД: {report.okved}")
        profile = "✅ Грузоперевозки и экспедирование" if report.okved.startswith(("49.41", "49.42", "52.29", "52.10", "52.21")) else "⚠️ Непрофильный ОКВЭД — проверь договор"
        lines.append(f"Профиль: {profile}")
    if report.address:
        lines.append(f"Адрес: {report.address}")
    note = "Данные ЕГРЮЛ/ЕГРИП на дату проверки"
    if report.from_cache:
        note += " (из кэша за 24 ч)"
    lines.extend(["", f"_{note}_", "Реестр экспедиторов ГосЛог: https://sicmt.ru"])
    return "\n".join(lines)
