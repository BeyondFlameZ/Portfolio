"""
Два языка в одном боте. Язык выбирается на каждого пользователя:
сохранённый выбор (кнопка 🇬🇧/🇷🇺 в меню) → язык Telegram → DEFAULT_LANG.
tr("по-русски", "in English") — строка на языке текущего апдейта; D() — каталог (data / data_en).
"""
import contextvars

import config
import data
import data_en

LANG: contextvars.ContextVar[str] = contextvars.ContextVar("lang", default=config.DEFAULT_LANG)
RU_CODES = ("ru", "uk", "be", "kk", "ky", "uz", "hy", "az", "tg")


def en() -> bool:
    return LANG.get() == "en"


def tr(ru: str, en_: str) -> str:
    return en_ if en() else ru


def D():
    return data_en if en() else data


def detect(code: str | None) -> str:
    """Язык по language_code из Telegram; нет кода — язык по умолчанию."""
    if not code:
        return config.DEFAULT_LANG
    return "ru" if code.lower().split("-")[0] in RU_CODES else "en"


class use_lang:
    """with use_lang('en'): ... — временно переключить язык (напоминания, сообщения клиенту из админки)."""
    def __init__(self, lang):
        self.lang = lang or config.DEFAULT_LANG

    def __enter__(self):
        self.tok = LANG.set(self.lang)

    def __exit__(self, *a):
        LANG.reset(self.tok)
