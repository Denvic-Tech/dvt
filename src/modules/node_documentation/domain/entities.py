from dataclasses import dataclass


SUPPORTED_LOCALES = frozenset({"en", "ru"})
DEFAULT_FALLBACK_LOCALE = "ru"


def normalize_requested_locale(locale: str) -> str:
    normalized = locale.strip().lower().split("-", 1)[0]
    if normalized in SUPPORTED_LOCALES:
        return normalized
    return DEFAULT_FALLBACK_LOCALE


@dataclass(frozen=True)
class PublishedNodeDocumentation:
    node_name: str
    locale: str
    content: str
