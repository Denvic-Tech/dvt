from typing import Optional
from src.enums import Locales

SUPPORTED_LOCALES = {locale.value: locale for locale in Locales}  # {'en': Locales.EN, 'ru': Locales.RU}


def detect_locale_from_header(header: Optional[str]) -> Locales:
    if not header:
        return Locales.EN  # Язык по умолчанию

    parts = header.split(",")
    lang_q_pairs = []

    for part in parts:
        if ";q=" in part:
            lang, q = part.split(";q=")

            try:
                lang_q_pairs.append((lang.strip().lower(), float(q)))

            except ValueError:
                continue
        else:
            lang_q_pairs.append((part.strip().lower(), 1.0))

    # Сортировка по q убыванию
    sorted_langs = sorted(lang_q_pairs, key=lambda x: x[1], reverse=True)

    for lang, _ in sorted_langs:
        base_lang = lang.split("-")[0]  # Преобразуем ru-RU → ru
        if base_lang in SUPPORTED_LOCALES:
            return SUPPORTED_LOCALES[base_lang]

    return Locales.EN  # fallback


def detect_locale(x_language: Optional[str], accept_language: Optional[str]) -> Locales:
    if x_language:
        lang = x_language.lower().split("-")[0]  # безопасно: 'ru-RU' → 'ru'
        if lang in Locales.__members__.values():
            return Locales(lang)

        if lang in [l.value for l in Locales]:
            return Locales(lang)

    return detect_locale_from_header(accept_language)

