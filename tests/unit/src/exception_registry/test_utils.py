import sys

from fastapi import HTTPException

from src.exception_registry.exception_types import ExceptionCategory, ExceptionType
from src.exception_registry.registered_exception import RegisteredException, RegisteredHTTPException
from src.exception_registry.utils import (
    is_exception_in_registry,
    is_registered_exception,
    register_custom_exception,
    register_http_exception,
)


def test_register_custom_exception_decorator_registers_wrapper():
    @register_custom_exception(
        exc_name="CUSTOM_WRAPPED",
        exc_code="CUST_WRAP_001",
        exc_description="Wrapped",
        exc_category=ExceptionCategory.DB.value,
    )
    class WrappedError(Exception):
        pass

    assert issubclass(WrappedError, RegisteredException)
    assert WrappedError.name == "CUSTOM_WRAPPED"
    assert WrappedError.response_model.__name__ == "WrappedError"

    module = sys.modules[register_custom_exception.__module__]
    assert getattr(module, "WrappedError") is WrappedError

    instance = WrappedError(description="details")
    assert is_registered_exception(instance) is True
    assert is_exception_in_registry(instance) is True


def test_register_http_exception_decorator_registers_wrapper():
    @register_http_exception(
        exc_name="HTTP_WRAPPED",
        exc_code="HTTP_WRAP_001",
        exc_description="Wrapped HTTP",
        exc_category=ExceptionCategory.SERVICE_GATEWAY_ADMIN.value,
    )
    class WrappedHttpError(Exception):
        pass

    assert issubclass(WrappedHttpError, RegisteredHTTPException)
    assert WrappedHttpError.type == ExceptionType.HTTP_GENERATED.value

    instance = WrappedHttpError(status_code=403, detail="forbidden")
    assert is_registered_exception(instance) is True
    assert is_exception_in_registry(instance) is True


def test_is_registered_exception_for_http_detail_dict_and_string():
    detail = {
        "name": "HTTP_DETAIL",
        "code": "HTTP_DETAIL_001",
        "description": "Detail",
        "category": ExceptionCategory.UNKNOWN.value,
        "type": ExceptionType.HTTP_GENERATED.value,
    }
    exc = HTTPException(status_code=400, detail=detail)
    assert is_registered_exception(exc) is True

    exc_string = HTTPException(status_code=400, detail="plain")
    assert is_registered_exception(exc_string) is False


def test_is_registered_exception_rejects_unknown_payload_keys():
    exc = HTTPException(status_code=400, detail={"unexpected": "value"})
    assert is_registered_exception(exc) is False


def test_is_registered_exception_for_custom_like_object():
    class CustomLike:
        name = "CUSTOM_LIKE"
        code = "CL_001"
        category = ExceptionCategory.UNKNOWN.value
        type = ExceptionType.CUSTOM.value
        description = "Custom like"
        exc_data = "details"

    assert is_registered_exception(CustomLike()) is True
