import re
import sys
from typing import Any

from src.exception_registry.registered_exception import RegisteredException, RegisteredHTTPException
from src.exception_registry.exception_types import ExceptionCategory
from fastapi import HTTPException

from src.exception_registry.registry import ERROR_REGISTRY


_ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")



def register_custom_exception(
        exc_name: str,
        exc_code: str,
        exc_description: str,
        exc_category: str = ExceptionCategory.UNKNOWN.value,
):
    """
    Декоратор для создания RegisteredException на основе существующего исключения

    Args:
        exc_name: Уникальное название ошибки
        exc_code: Код ошибки
        exc_description: Описание ошибки
        exc_category: Категория ошибки
    """
    def decorator(cls: type[Exception]) -> type[RegisteredException]:

        # Создаем новый класс, наследующий от RegisteredException
        class RegisteredExceptionWrapper(RegisteredException):
            # Статические атрибуты для регистрации
            name = exc_name
            code = exc_code
            category = exc_category
            description = exc_description

        # Сохраняем оригинальное имя класса
        RegisteredExceptionWrapper.__name__ = cls.__name__
        RegisteredExceptionWrapper.__qualname__ = cls.__qualname__
        # Обновляем response_model
        RegisteredExceptionWrapper.update_response_model(__name__=cls.__name__, __qualname__=cls.__qualname__)

        # Регаем класс в глобальной области видимости, чтобы можно было picklить его (для loguru в многопоточке)
        original_module = sys.modules[register_custom_exception.__module__]
        setattr(original_module, cls.__name__, RegisteredExceptionWrapper)

        return RegisteredExceptionWrapper

    return decorator


def register_http_exception(
        exc_name: str,
        exc_code: str,
        exc_description: str,
        exc_category: str = ExceptionCategory.UNKNOWN.value,
):
    """
    Декоратор для создания RegisteredHTTPExceptionWrapper, Которое отлавливается самим FastAPI на основе существующего исключения

    Args:
        exc_name: Уникальное название ошибки
        exc_code: Код ошибки
        exc_description: Описание ошибки
        exc_category: Категория ошибки
    """

    def decorator(cls: type[Exception]) -> type[RegisteredHTTPException]:
        # Создаем новый класс, наследующий от RegisteredException
        class RegisteredHTTPExceptionWrapper(RegisteredHTTPException):
            # Статические атрибуты для регистрации
            name = exc_name
            code = exc_code
            category = exc_category
            description = exc_description

        # Сохраняем оригинальное имя класса
        RegisteredHTTPExceptionWrapper.__name__ = cls.__name__
        RegisteredHTTPExceptionWrapper.__qualname__ = cls.__qualname__
        # Обновляем response_model
        RegisteredHTTPExceptionWrapper.update_response_model(__name__=cls.__name__, __qualname__=cls.__qualname__)
        original_module = sys.modules[register_http_exception.__module__]
        setattr(original_module, cls.__name__, RegisteredHTTPExceptionWrapper)

        return RegisteredHTTPExceptionWrapper

    return decorator


def is_registered_exception(exc: Exception) -> bool:
    if isinstance(exc, RegisteredHTTPException) or isinstance(exc, RegisteredException):
        return True

    if isinstance(exc, HTTPException):
        data: Any = exc.detail

        if isinstance(data, str):
            return False

        exc_attrs = {*RegisteredHTTPException.__annotations__.keys(), *RegisteredException.__annotations__.keys()}

        # Проверяем, что все аттрибуты совпадают
        for attr in data:
            if attr not in exc_attrs:
                return False
        return True
    else:
        exc_attrs = RegisteredException.__annotations__
        for attr in exc_attrs.keys():
            try:
                if not getattr(exc, attr):
                    return False
            except AttributeError:
                return False
        return True

def is_exception_in_registry(exc: Exception) -> bool:

    if isinstance(exc, RegisteredHTTPException) or isinstance(exc, RegisteredException):
        return True

    if isinstance(exc, HTTPException):
        data: Any = exc.detail

        # Не можем получить данные - значит нету
        if isinstance(data, str):
            return False

        # Проверяем, что данные ошибки зареганы в реестре
        if not ERROR_REGISTRY.get_errors_by_filters(**data):
            return False
        return True
    else:
        current_exc_attrs = exc.__annotations__
        data = dict()
        try:
            for attr in current_exc_attrs:
                data[attr] = getattr(exc, attr)
        except AttributeError:
            return False

        # Проверяем, что данные ошибки зареганы в реестре
        if not ERROR_REGISTRY.get_errors_by_filters(**data):
            return False
        return True


def safe_exception_message(
    exc: Exception | str,
    *,
    max_length: int | None = 1000,
) -> str:
    """
    Convert exception to a safe API message.

    - removes ANSI escape sequences
    - converts exception to string safely
    - optionally truncates long messages
    """

    if isinstance(exc, Exception):
        message = str(exc) or exc.__class__.__name__
    else:
        message = str(exc)

    # remove ANSI terminal formatting
    message = _ANSI_ESCAPE_RE.sub("", message)

    # trim overly long messages (e.g. SQL dumps)
    if max_length is not None and len(message) > max_length:
        message = message[:max_length].rstrip() + "..."

    return message
