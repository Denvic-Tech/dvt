import re


HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-F]{6}$")

DEFAULT_CATEGORY_COLOR = "#64748B"

CATEGORY_COLORS: dict[str, str] = {
    "API": "#6366F1",
    "Connections": "#0891B2",
    "Custom": DEFAULT_CATEGORY_COLOR,
    "Extraction": "#059669",
    "Internal": DEFAULT_CATEGORY_COLOR,
    "JSON": "#D97706",
    "Mock Data": DEFAULT_CATEGORY_COLOR,
    "Primitive": DEFAULT_CATEGORY_COLOR,
    "Testing": DEFAULT_CATEGORY_COLOR,
    "Tool": "#E11D48",
    "Transform": "#DC2626",
    "Widgets": "#7C3AED",
    "Writing": "#0D9488",
}


def _validate_hex_color(color: str) -> str:
    normalized_color = color.upper()
    if not HEX_COLOR_PATTERN.fullmatch(normalized_color):
        raise ValueError(f"Invalid category color '{color}'. Expected hex format '#RRGGBB'.")
    return normalized_color


def resolve_category_color(category: str) -> str:
    return _validate_hex_color(CATEGORY_COLORS.get(category, DEFAULT_CATEGORY_COLOR))
