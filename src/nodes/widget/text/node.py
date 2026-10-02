from enum import Enum
from typing import Optional, Literal

from src.node_dsl import WidgetBaseNode, InputField


class FontFamily(str, Enum):
    """Доступные семейства шрифтов"""
    ARIAL = "Arial"
    HELVETICA = "Helvetica"
    TIMES_NEW_ROMAN = "Times New Roman"
    COURIER = "Courier"
    VERDANA = "Verdana"
    GEORGIA = "Georgia"
    MONOSPACE = "monospace"
    SANS_SERIF = "sans-serif"
    SERIF = "serif"


class TextAlign(str, Enum):
    """Выравнивание текста"""
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    JUSTIFY = "justify"


class FontWeight(str, Enum):
    """Насыщенность шрифта"""
    NORMAL = "normal"
    BOLD = "bold"
    LIGHTER = "lighter"
    BOLDER = "bolder"
    _100 = "100"
    _200 = "200"
    _300 = "300"
    _400 = "400"
    _500 = "500"
    _600 = "600"
    _700 = "700"
    _800 = "800"
    _900 = "900"


class Text(WidgetBaseNode):
    TITLE = "Add Text field"
    ICON_KEY = "text"
    EMOJI = "📝"
    CATEGORY = "Widgets"

    # Основное содержимое
    text_content: str = InputField(
        agent_description=(
            "Set the explanatory text displayed on the pipeline canvas, such as purpose, "
            "assumptions, or operating notes. This widget has no data-processing behavior; its "
            "text does not create variables or enforce pipeline rules."
        ),
        default="",
        description="Текст для отображения"
    )

    font_family: FontFamily = InputField(
        agent_description=(
            "Choose one of the supported font-family enum values for the canvas annotation. Prefer "
            "a readable family consistent with nearby notes; this has no execution effect."
        ),
        default=FontFamily.ARIAL,
        description="Семейство шрифта"
    )

    font_size: int = InputField(
        agent_description=(
            "Choose a font size within 8..72 using the widget's point-size setting. Keep "
            "annotations readable at normal canvas zoom; use larger sizes for headings."
        ),
        default=14,
        min_value=8,
        max_value=72,
        description="Размер шрифта в пунктах"
    )

    font_weight: FontWeight = InputField(
        agent_description=(
            "Choose a supported weight such as normal, bold, or a declared numeric string. Use "
            "emphasis sparingly to distinguish headings from explanatory text."
        ),
        default=FontWeight.NORMAL,
        description="Насыщенность шрифта"
    )

    font_style: Literal["normal", "italic", "oblique"] = InputField(
        agent_description=(
            "Choose normal, italic, or oblique for the annotation. Normal is the default and "
            "usually the most readable for longer operational notes."
        ),
        default="normal",
        description="Стиль шрифта"
    )

    # Цвета
    text_color: str = InputField(
        agent_description=(
            "Set the text color as a valid HEX string such as #000000. Ensure sufficient contrast "
            "with the chosen background and the canvas."
        ),
        default="#000000",
        description="Цвет текста в HEX формате (например, #FF0000)"
    )

    background_color: str = InputField(
        agent_description=(
            "Set a valid HEX background color, optionally including alpha; #ffffff00 is "
            "transparent. Choose a background that keeps the annotation legible without hiding "
            "nearby graph content."
        ),
        default="#ffffff00",  # По умолчанию прозрачный (или пустая строка)
        description="Цвет фона в HEX формате"
    )

    # Рамка и выравнивание
    border_width: int = InputField(
        agent_description=(
            "Set a border width from 0 to 20 pixels. Zero hides the border; use a small positive "
            "width when the note needs a visible boundary."
        ),
        default=0,
        min_value=0,
        max_value=20,
        description="Ширина рамки в пикселях"
    )

    border_color: str = InputField(
        agent_description=(
            "Choose a HEX border color that contrasts with the background. It is visible only when "
            "border_width is positive."
        ),
        default="#000000",
        description="Цвет рамки"
    )

    # Выравнивание и отступы
    text_align: TextAlign = InputField(
        agent_description=(
            "Choose left, center, right, or justify for the displayed text. Prefer left alignment "
            "for longer explanatory notes and reserve centered text for short labels."
        ),
        default=TextAlign.LEFT,
        description="Выравнивание текста"
    )

    def process(self):
        pass
