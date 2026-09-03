import pytest

from src.exception_registry.exception_types import ExceptionCategory, ExceptionType
from src.exception_registry.registered_exception import RegisteredException, RegisteredHTTPException
from src.exception_registry.registry import ERROR_REGISTRY, ExceptionRegistry


def test_exception_registry_singleton():
    assert ExceptionRegistry() is ERROR_REGISTRY


def test_register_error_raises_on_duplicate():
    class DuplicateError(RegisteredException):
        name = "DUPLICATE_ERROR"
        code = "DUP_001"
        description = "Duplicate error"
        category = ExceptionCategory.UNKNOWN.value

    # Class is already registered via __init_subclass__
    with pytest.raises(ValueError):
        ERROR_REGISTRY.register_error(DuplicateError)


def test_delete_error_removes_custom_errors_only():
    class CustomError(RegisteredException):
        name = "CUSTOM_DELETE"
        code = "CUST_001"
        description = "Custom error"
        category = ExceptionCategory.UNKNOWN.value

    class HttpGeneratedError(RegisteredHTTPException):
        name = "HTTP_DELETE"
        code = "HTTP_001"
        description = "HTTP error"
        category = ExceptionCategory.UNKNOWN.value

    assert ERROR_REGISTRY.delete_error(name="CUSTOM_DELETE", code="CUST_001") is True
    assert ERROR_REGISTRY.get_errors_by_filters(name="CUSTOM_DELETE") == []

    assert ERROR_REGISTRY.delete_error(name="HTTP_DELETE", code="HTTP_001") is False
    assert ERROR_REGISTRY.get_errors_by_filters(name="HTTP_DELETE") != []


def test_get_errors_by_filters_and_serialize():
    class FirstError(RegisteredException):
        name = "FIRST_ERROR"
        code = "ERR_001"
        description = "First"
        category = ExceptionCategory.UNKNOWN.value

    class SecondError(RegisteredException):
        name = "SECOND_ERROR"
        code = "ERR_002"
        description = "Second"
        category = ExceptionCategory.DB.value

    by_name = ERROR_REGISTRY.get_errors_by_filters(name="FIRST_ERROR")
    assert len(by_name) == 1
    assert by_name[0].name == "FIRST_ERROR"

    by_category = ERROR_REGISTRY.get_errors_by_filters(category=ExceptionCategory.DB.value)
    assert len(by_category) == 1
    assert by_category[0].code == "ERR_002"

    serialized_single = ERROR_REGISTRY.serialize_exceptions(by_name)
    assert serialized_single["code"] == "ERR_001"

    serialized_multi = ERROR_REGISTRY.serialize_exceptions([FirstError, SecondError])
    assert isinstance(serialized_multi, list)
    assert {item["code"] for item in serialized_multi} == {"ERR_001", "ERR_002"}


def test_list_serialized_errors_and_schemas():
    class SchemaError(RegisteredException):
        name = "SCHEMA_ERROR"
        code = "SCHEMA_001"
        description = "Schema error"
        category = ExceptionCategory.UNKNOWN.value

    serialized = ERROR_REGISTRY.list_serialized_errors()
    assert serialized == [SchemaError.serialize()]

    schemas = ERROR_REGISTRY.get_schemas()
    assert len(schemas) == 1
    assert schemas[0].__name__ == "SchemaError"
    assert SchemaError.type == ExceptionType.CUSTOM.value
