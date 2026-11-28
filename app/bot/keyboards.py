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
        [{"type": "callback", "text": "🛣 Расстояние и ₽/км", "payload": "screen:dist", "intent": "default"}],
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


def calc_result_keyboard(order_id: int) -> list[list[dict]]:
    return [
        [{"type": "callback", "text": "✏️ Другая ставка водителя", "payload": f"calc:recalc:{order_id}", "intent": "default"}],
        [{"type": "callback", "text": "← В меню", "payload": "screen:home_new", "intent": "default"}],
    ]


def ttn_driver_keyboard() -> list[list[dict]]:
    return [[{"type": "callback", "text": "✅ Готово (отправить PDF логисту)", "payload": "ttn:done", "intent": "positive"}]]


def admin_keyboard(free_beta: bool = True) -> list[list[dict]]:
    action_label = "💳 Включить платный режим" if free_beta else "🟢 Включить бесплатную бету"
    return [
        [
            {"type": "callback", "text": "📊 Сводка", "payload": "admin:stats", "intent": "default"},
            {"type": "callback", "text": "⚠️ Ошибки парсера", "payload": "admin:fails", "intent": "default"},
        ],
        [{"type": "callback", "text": action_label, "payload": "admin:toggle_beta", "intent": "default"}],
        [
            {"type": "callback", "text": "📢 Рассылка", "payload": "admin:broadcast", "intent": "default"},
            {"type": "callback", "text": "← В меню", "payload": "screen:home_new", "intent": "default"},
        ],
    ]
