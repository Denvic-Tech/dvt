from typing import Any

from starlette.responses import JSONResponse

from src.exception_registry.exception_types import ExceptionCategory, ExceptionType
from src.exception_registry.registered_exception import RegisteredHTTPException, RegisteredException
from src.exception_registry.registry import ERROR_REGISTRY
from src.exception_registry.utils import is_registered_exception, is_exception_in_registry
from fastapi import HTTPException

from src.logger import logger


async def exception_handler(request, exc):

    if isinstance(exc, RegisteredHTTPException) or isinstance(exc, RegisteredException):
        return JSONResponse(exc.serialize(), status_code=getattr(exc, "status_code", 500))

    if is_registered_exception(exc) and is_exception_in_registry(exc):
        if isinstance(exc, HTTPException):
            reg_exc = ERROR_REGISTRY.get_errors_by_filters(**exc.detail)[0]

            return JSONResponse(reg_exc.serialize(), status_code=exc.status_code)
        else:
            current_exc_attrs = exc.__annotations__
            data = dict()
            for attr in current_exc_attrs:
                data[attr] = getattr(exc, attr)
            reg_exc = ERROR_REGISTRY.get_errors_by_filters(**data)[0]
            return JSONResponse(reg_exc.serialize(), status_code=404)
    elif is_registered_exception(exc) and not is_exception_in_registry(exc):
        # Если ошибка HTTP, берем данные для заполнения из detail
        if isinstance(exc, HTTPException):
            exc_data: Any = exc.detail

            if isinstance(exc_data, str):
                # Автоматически зарегается при инициализации класса
                class UnknownHTTPException(RegisteredHTTPException):
                    name: str = "UNKNOWN"
                    code: str = "UNKNOWN_CODE"
                    category: str = ExceptionCategory.UNKNOWN.value
                    description: str = exc_data
                    type: str = ExceptionType.HTTP_GENERATED.value

                return JSONResponse(UnknownHTTPException.serialize(), status_code=exc.status_code)
            else:
                # Автоматически зарегается при инициализации класса
                class UnknownHTTPException(RegisteredHTTPException):
                    name: str = exc_data.get("name")
                    code: str = exc_data.get("code")
                    category: str = exc_data.get("category")
                    description: str = exc_data.get("description")
                    type: str = exc_data.get("type")

                return JSONResponse(UnknownHTTPException.serialize(), status_code=exc.status_code)

        # Если обычный Exception - то берем из __annotations__ с получением всех значений
        else:

            current_exc_attrs = exc.__annotations__
            data = dict()
            for attr in current_exc_attrs:
                data[attr] = getattr(exc, attr)

            # Автоматически зарегается при инициализации класса
            class UnknownException(RegisteredHTTPException):
                name: str = data.get("name")
                code: str = data.get("code")
                category: str = data.get("category")
                description: str = data.get("description")
                type: str = data.get("type")

            return JSONResponse(UnknownException.serialize(), status_code=exc.status_code)

    # Значит ошибка не зарегана в реестре, и по сигнатуре тоже не подходит
    else:

        # Формируем как можем
        class UnknownHTTPException(RegisteredHTTPException):
            name: str = str(exc.__class__.__name__)
            code: str = exc.status_code if isinstance(exc, HTTPException) else "UNKNOWN_ERROR"
            category: str = ExceptionCategory.UNKNOWN.value
            description: str = exc.detail if isinstance(exc, HTTPException) else str(exc)
            type: str = ExceptionType.HTTP_GENERATED.value

        return JSONResponse(UnknownHTTPException.serialize(), status_code=exc.status_code if isinstance(exc, HTTPException) else 500)
