TAX_SHORT_NAMES: dict[str, str] = {
    "osno_22": "ОСНО 22%",
    "usn_5_nds": "УСН + НДС 5%",
    "usn_6": "УСН 6% • Рейс",
    "usn_6_agent": "УСН 6% • Агент",
    "usn_15": "УСН 15%",
}


def main_menu_keyboard() -> list[list[dict]]:
    return [
        [{"type": "callback", "text": "🧮 Стоп-цена (Маржа)", "payload": "screen:calc", "intent": "positive"}],
        [
            {"type": "callback", "text": "🛡 ИНН", "payload": "screen:inn", "intent": "default"},
            {"type": "callback", "text": "📄 ТТН", "payload": "screen:ttn", "intent": "default"},
        ],
        [{"type": "callback", "text": "⚙️ Налоговый режим", "payload": "screen:tax", "intent": "default"}],
    ]


def tax_modes_keyboard(current_mode: str) -> list[list[dict]]:
    def btn(code: str) -> dict:
        is_active = code == current_mode
        mark = "✅ " if is_active else ""
        return {
            "type": "callback",
            "text": f"{mark}{TAX_SHORT_NAMES[code]}",
            "payload": f"tax:{code}",
            "intent": "positive" if is_active else "default",
        }

    return [
        [btn("osno_22"), btn("usn_5_nds")],
        [btn("usn_6"), btn("usn_6_agent")],
        [btn("usn_15"), {"type": "callback", "text": "← Назад", "payload": "screen:home", "intent": "default"}],
    ]


def back_to_home_keyboard() -> list[list[dict]]:
    return [[{"type": "callback", "text": "← В меню", "payload": "screen:home", "intent": "default"}]]


def keep_result_menu_keyboard() -> list[list[dict]]:
    return [[{"type": "callback", "text": "← В меню", "payload": "screen:home_new", "intent": "default"}]]
