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
    EMOJI = "📝"
    CATEGORY = "Widgets"

    # Основное содержимое
    text_content: str = InputField(
        default="",
        description="Текст для отображения"
    )

    font_family: FontFamily = InputField(
        default=FontFamily.ARIAL,
        description="Семейство шрифта"
    )

    font_size: int = InputField(
        default=14,
        min_value=8,
        max_value=72,
        description="Размер шрифта в пунктах"
    )

    font_weight: FontWeight = InputField(
        default=FontWeight.NORMAL,
        description="Насыщенность шрифта"
    )

    font_style: Literal["normal", "italic", "oblique"] = InputField(
        default="normal",
        description="Стиль шрифта"
    )

    # Цвета
    text_color: str = InputField(
        default="#000000",
        description="Цвет текста в HEX формате (например, #FF0000)"
    )

    background_color: str = InputField(
        default="#ffffff00",  # По умолчанию прозрачный (или пустая строка)
        description="Цвет фона в HEX формате"
    )

    # Рамка и выравнивание
    border_width: int = InputField(
        default=0,
        min_value=0,
        max_value=20,
        description="Ширина рамки в пикселях"
    )

    border_color: str = InputField(
        default="#000000",
        description="Цвет рамки"
    )

    # Выравнивание и отступы
    text_align: TextAlign = InputField(
        default=TextAlign.LEFT,
        description="Выравнивание текста"
    )

    def process(self):
        pass
