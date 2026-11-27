TAX_SHORT_NAMES: dict[str, str] = {
    "osno_22": "ОСНО 22%",
    "usn_5_nds": "УСН + НДС 5%",
    "usn_6": "УСН 6% • Рейс",
    "usn_6_agent": "УСН 6% • Агент",
    "usn_15": "УСН 15%",
}


def main_menu_keyboard() -> list[list[dict]]:
    return [
        [{"type": "callback", "text": "🧮 Стоп-цена (Маржа)", "payload": "screen:calc"}],
        [
            {"type": "callback", "text": "🛡 ИНН", "payload": "screen:inn"},
            {"type": "callback", "text": "📄 ТТН", "payload": "screen:ttn"},
        ],
        [{"type": "callback", "text": "⚙️ Налоговый режим", "payload": "screen:tax"}],
    ]


def tax_modes_keyboard(current_mode: str) -> list[list[dict]]:
    def btn(code: str) -> dict:
        mark = "✅ " if code == current_mode else ""
        return {"type": "callback", "text": f"{mark}{TAX_SHORT_NAMES[code]}", "payload": f"tax:{code}"}

    return [
        [btn("osno_22"), btn("usn_5_nds")],
        [btn("usn_6"), btn("usn_6_agent")],
        [btn("usn_15"), {"type": "callback", "text": "← Назад", "payload": "screen:home"}],
    ]


def back_to_home_keyboard() -> list[list[dict]]:
    return [[{"type": "callback", "text": "← В меню", "payload": "screen:home"}]]
