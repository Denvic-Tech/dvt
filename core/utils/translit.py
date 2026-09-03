import re
from unidecode import unidecode

_non_word = re.compile(r"\W+")


def ru2en(name: str) -> str:
    """
    Транслитерирует русскую строку → ASCII, превращая её
    в валидный идентификатор/имя колонки для любых СУБД.
    Гарантирует уникальность (возвращая пару result, changed).
    """
    ascii_name = unidecode(name)
    ascii_name = _non_word.sub("_", ascii_name)
    ascii_name = ascii_name.strip("_").lower()
    if ascii_name and ascii_name[0].isdigit():
        ascii_name = f"c_{ascii_name}"
    return ascii_name
