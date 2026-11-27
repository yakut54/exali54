TAX_SHORT_NAMES: dict[str, str] = {
    "osno_22": "ОСНО • НДС 22%",
    "usn_6": "УСН 6% • Перевозка",
    "usn_6_agent": "УСН 6% • Агент",
    "usn_15": "УСН 15%",
    "usn_5_nds": "УСН + НДС 5%",
}


def main_menu_keyboard() -> list[list[dict]]:
    return [
        [{"type": "callback", "text": "🧮 Стоп-цена (Маржа)", "payload": "screen:calc"}],
        [
            {"type": "callback", "text": "🛡 Проверить ИНН", "payload": "screen:inn"},
            {"type": "callback", "text": "📄 Сбор ТТН", "payload": "screen:ttn"},
        ],
        [{"type": "callback", "text": "⚙️ Налоговый режим", "payload": "screen:tax"}],
    ]


def tax_modes_keyboard(current_mode: str) -> list[list[dict]]:
    rows: list[list[dict]] = []
    for code, title in TAX_SHORT_NAMES.items():
        prefix = "✅ " if code == current_mode else ""
        rows.append([{"type": "callback", "text": f"{prefix}{title}", "payload": f"tax:{code}"}])
    rows.append([{"type": "callback", "text": "← В главное меню", "payload": "screen:home"}])
    return rows


def back_to_home_keyboard() -> list[list[dict]]:
    return [[{"type": "callback", "text": "← В главное меню", "payload": "screen:home"}]]
