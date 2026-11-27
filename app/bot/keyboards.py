def main_menu_keyboard() -> list[list[dict]]:
    return [
        [{"type": "callback", "text": "🏛 Сменить налоговый режим", "payload": "menu:tax"}],
        [
            {"type": "callback", "text": "🧮 Как считать маржу", "payload": "menu:help_calc"},
            {"type": "callback", "text": "🛡 Проверить ИНН", "payload": "menu:help_inn"},
        ],
    ]


def tax_modes_keyboard() -> list[list[dict]]:
    return [
        [{"type": "callback", "text": "ОСНО (с НДС 22%)", "payload": "tax:osno_22"}],
        [
            {"type": "callback", "text": "УСН 6% (перевозка)", "payload": "tax:usn_6"},
            {"type": "callback", "text": "УСН 6% (агент)", "payload": "tax:usn_6_agent"},
        ],
        [
            {"type": "callback", "text": "УСН 15%", "payload": "tax:usn_15"},
            {"type": "callback", "text": "УСН + НДС 5%", "payload": "tax:usn_5_nds"},
        ],
    ]
