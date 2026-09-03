import asyncio
import json

from fastapi import HTTPException

from src.exception_registry.exception_types import ExceptionCategory, ExceptionType
from src.exception_registry.handlers import exception_handler
from src.exception_registry.registered_exception import RegisteredException, RegisteredHTTPException
from src.exception_registry.registry import ERROR_REGISTRY


def _parse_body(response):
    return json.loads(response.body.decode("utf-8"))


def test_exception_handler_registered_exception():
    class SimpleError(RegisteredException):
        name = "SIMPLE"
        code = "SIMPLE_001"
        description = "Simple"
        category = ExceptionCategory.UNKNOWN.value

    exc = SimpleError()
    response = asyncio.run(exception_handler(None, exc))
    body = _parse_body(response)

    assert response.status_code == 500
    assert body["name"] == "SIMPLE"
    assert body["code"] == "SIMPLE_001"


def test_exception_handler_registered_http_exception():
    class SimpleHttpError(RegisteredHTTPException):
        name = "HTTP_SIMPLE"
        code = "HTTP_001"
        description = "HTTP error"
        category = ExceptionCategory.UNKNOWN.value

    exc = SimpleHttpError(status_code=404, detail="missing")
    response = asyncio.run(exception_handler(None, exc))
    body = _parse_body(response)

    assert response.status_code == 404
    assert body["name"] == "HTTP_SIMPLE"
    assert body["type"] == ExceptionType.HTTP_GENERATED.value


def test_exception_handler_registered_http_exception_uses_class_status_code():
    class DefaultHttpError(RegisteredHTTPException):
        name = "HTTP_DEFAULT"
        code = "HTTP_409"
        description = "Conflict"
        category = ExceptionCategory.UNKNOWN.value
        status_code = 409
        detail = "conflict detail"

    exc = DefaultHttpError()
    response = asyncio.run(exception_handler(None, exc))
    body = _parse_body(response)

    assert exc.status_code == 409
    assert exc.detail == "conflict detail"
    assert response.status_code == 409
    assert body["name"] == "HTTP_DEFAULT"


def test_exception_handler_http_exception_with_registered_detail():
    class DetailHttpError(RegisteredHTTPException):
        name = "DETAIL_HTTP"
        code = "DETAIL_001"
        description = "Detail"
        category = ExceptionCategory.SERVICE_GATEWAY_ADMIN.value

    detail = {
        "name": "DETAIL_HTTP",
        "code": "DETAIL_001",
        "description": "Detail",
        "category": ExceptionCategory.SERVICE_GATEWAY_ADMIN.value,
        "type": ExceptionType.HTTP_GENERATED.value,
    }

    exc = HTTPException(status_code=400, detail=detail)
    response = asyncio.run(exception_handler(None, exc))
    body = _parse_body(response)

    assert response.status_code == 400
    assert body["code"] == "DETAIL_001"
    assert body["name"] == "DETAIL_HTTP"

    # Ensure registry lookup was used
    assert ERROR_REGISTRY.get_errors_by_filters(name="DETAIL_HTTP")


def test_exception_handler_http_exception_with_string_detail():
    exc = HTTPException(status_code=418, detail="teapot")
    response = asyncio.run(exception_handler(None, exc))
    body = _parse_body(response)

    assert response.status_code == 418
    assert body["name"] == "HTTPException"
    assert body["code"] == 418
    assert body["description"] == "teapot"
