from typing import Union

from src.exception_registry.registry import ERROR_REGISTRY

RegisteredExceptionSchema = Union[*ERROR_REGISTRY.get_schemas()]