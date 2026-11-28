import json
import re
from pathlib import Path

_DATA = Path(__file__).resolve().parent.parent / "data" / "ru_cities.json"
ALL_CITIES: set[str] = set(json.loads(_DATA.read_text(encoding="utf-8")))

def _norm(value: str) -> str:
    return " ".join(value.lower().replace("ё", "е").replace("-", " ").split())

CITY_NORM_MAP = {_norm(city): city for city in ALL_CITIES}
CITY_STEMS = {re.sub(r"[^а-я]", "", city.lower().replace("ё", "е"))[:6]
              for city in ALL_CITIES if len(re.sub(r"[^а-я]", "", city.lower())) >= 6}

CITY_ALIASES = {
    "мск": "Москва", "спб": "Санкт-Петербург", "питер": "Санкт-Петербург",
    "нск": "Новосибирск", "новосиб": "Новосибирск", "екб": "Екатеринбург",
    "кзн": "Казань", "крд": "Краснодар", "рнд": "Ростов-на-Дону",
    "нн": "Нижний Новгород", "члб": "Челябинск", "челяба": "Челябинск",
    "челяюинск": "Челябинск", "крск": "Красноярск", "тмн": "Тюмень",
    "прм": "Пермь", "перьмь": "Пермь", "брн": "Барнаул", "кем": "Кемерово",
    "нвкз": "Новокузнецк", "ирк": "Иркутск", "уу": "Улан-Удэ",
    "срг": "Сургут", "нврт": "Нижневартовск", "мгн": "Магнитогорск",
    "орб": "Оренбург", "смр": "Самара", "тлт": "Тольятти", "влг": "Волгоград",
    "врн": "Воронеж", "срт": "Саратов", "пнз": "Пенза", "улн": "Ульяновск",
    "иж": "Ижевск", "крв": "Киров", "твр": "Тверь", "клг": "Калуга",
    "рзн": "Рязань", "блг": "Белгород", "лпц": "Липецк", "чбкс": "Чебоксары",
    "ств": "Ставрополь", "нврс": "Новороссийск", "астр": "Астрахань",
    "мхч": "Махачкала", "клнг": "Калининград", "мурм": "Мурманск",
    "арх": "Архангельск", "птз": "Петрозаводск", "влдв": "Владивосток",
    "влад": "Владивосток", "владивасток": "Владивосток", "хбр": "Хабаровск",
    "блгв": "Благовещенск", "якт": "Якутск", "нхд": "Находка",
    "усс": "Уссурийск", "ярик": "Ярославль", "ярсл": "Ярославль",
    "чебы": "Чебоксары", "влгд": "Волгодонск", "алмата": "Алматы",
}
CITY_ALIAS_MAP = CITY_ALIASES

def _known_matches(text: str) -> list[tuple[int, int]]:
    value = _norm(text)
    patterns = list(CITY_ALIAS_MAP) + sorted(CITY_NORM_MAP, key=len, reverse=True)
    spans = [m.span() for word in patterns
             for m in re.finditer(rf"(?<![а-я]){re.escape(word)}(?![а-я])", value)]
    spans += [m.span() for stem in CITY_STEMS
              for m in re.finditer(rf"(?<![а-я]){re.escape(stem)}[а-я-]*", value)]
    result = []
    for span in sorted(spans, key=lambda item: (item[0], -(item[1] - item[0]))):
        if not any(span[0] < end and start < span[1] for start, end in result):
            result.append(span)
    return result

def has_known_cities(text: str) -> bool:
    return len(_known_matches(text)) >= 2

def normalize_city_name(raw: str | None) -> str:
    value = " ".join((raw or "").strip().split()).strip(" ,.;:")
    key = _norm(value)
    if key in CITY_ALIASES:
        return CITY_ALIASES[key]
    if key in CITY_NORM_MAP:
        return CITY_NORM_MAP[key]
    return re.sub(r"^(?:г(?:ород)?|с(?:ело)?|пос(?:ёлок)?)[. ]+", "", value, flags=re.I)
