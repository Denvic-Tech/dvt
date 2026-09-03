import pytest

from src.exception_registry.registry import ERROR_REGISTRY


@pytest.fixture(autouse=True)
def clean_exception_registry():
    original = ERROR_REGISTRY._exceptions
    ERROR_REGISTRY._exceptions = {}
    try:
        yield
    finally:
        ERROR_REGISTRY._exceptions = original
