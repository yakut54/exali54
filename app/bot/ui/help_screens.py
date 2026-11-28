HELP_INTRO = (
    "**❓ Как пользоваться ботом**\n"
    "Выбери раздел или просто пришли заявку текстом.\n\n"
    "Я считаю маржу, проверяю ИНН, нахожу расстояние и собираю ТТН в PDF."
)

HELP_SECTIONS: dict[str, str] = {
    "calc": (
        "**🧮 Маржа и стоп-цена**\n"
        "Пришли маршрут и две ставки:\n"
        "`нск омск 20т 140 с ндс / 100 ип`\n\n"
        "Если известна только ставка клиента, я спрошу ставку перевозчика.\n"
        "Можно указать желаемую прибыль:\n`мск тлт 140 с ндс хочу 20к`\n\n"
        "Можно просто переслать пост из чата — посчитаю и соберу объявление для поиска машины."
    ),
    "distance": (
        "**🛣 Расстояние и ₽/км**\n"
        "Пришли два города:\n`Уссурийск Москва`\n\n"
        "Чтобы перевести сумму в ставку за километр:\n"
        "`Уссурийск Москва 750 тыс наличными`\n\n"
        "Покажу расстояние, сумму без НДС и с НДС 22%."
    ),
    "inn": (
        "**🛡 Проверка ИНН**\n"
        "Пришли 10 или 12 цифр ИНН:\n`7707083893`\n\n"
        "Покажу статус, дату регистрации, руководителя, ОКВЭД и адрес.\n"
        "Проверю профиль ОКВЭД и дам ссылку на реестр ГосЛог."
    ),
    "ttn": (
        "**📄 Сбор ТТН**\n"
        "Нажми «📄 ТТН» и отправь водителю ссылку.\n"
        "Водитель пришлёт фото страниц ТТН.\n\n"
        "Я отсею размытые и тёмные фото, соберу остальные страницы в PDF "
        "и отправлю документ логисту."
    ),
    "tax": (
        "**⚙️ Налоговый режим**\n"
        "Выбери режим в разделе «⚙️ Налоговый режим».\n\n"
        "Он влияет на НДС, налог, прибыль и минимальную ставку."
    ),
}


def help_text(section: str | None = None) -> str:
    return HELP_SECTIONS.get(section, HELP_INTRO)


def help_menu_keyboard() -> list[list[dict]]:
    return [
        [{"type": "callback", "text": "🧮 Маржа", "payload": "help:calc", "intent": "default"},
         {"type": "callback", "text": "🛣 Расстояние", "payload": "help:distance", "intent": "default"}],
        [{"type": "callback", "text": "🛡 ИНН", "payload": "help:inn", "intent": "default"},
         {"type": "callback", "text": "📄 ТТН", "payload": "help:ttn", "intent": "default"}],
        [{"type": "callback", "text": "⚙️ Налоги", "payload": "help:tax", "intent": "default"}],
        [{"type": "callback", "text": "← В меню", "payload": "screen:home", "intent": "default"}],
    ]


def help_section_keyboard() -> list[list[dict]]:
    return [[
        {"type": "callback", "text": "← Все разделы", "payload": "screen:help", "intent": "default"},
        {"type": "callback", "text": "🏠 В меню", "payload": "screen:home", "intent": "default"},
    ]]
