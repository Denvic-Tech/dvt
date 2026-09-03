from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from src.exception_registry.errors_list.gateway.exception_registry import ExceptionRegistryNotFound, \
    ExceptionRegistryValidationError
from src.exception_registry.registered_exception import RegisteredExceptionMessage
from src.exception_registry.registry import ERROR_REGISTRY
from src.exception_registry.exception_types import ExceptionCategory

r = router = APIRouter(prefix="/exceptions",
                       tags=["Exceptions"])


@r.get('/', responses={404: {"model": ExceptionRegistryNotFound.response_model}})
def get_exceptions(request: Request, name: str = None, code: str = None,
                   description: str = None, category: ExceptionCategory = None) -> JSONResponse:
    """
    Возвращает список всех зарегистрированных Exceptions если не переданы фильтры,
    иначе все объекты, подходящие под фильтры
    """

    filters = {}
    if name:
        filters["name"] = name
    if code:
        filters["code"] = code
    if description:
        filters["description"] = description
    if category:
        filters["category"] = category.value

    res = ERROR_REGISTRY.get_errors_by_filters(**filters)

    if res:
        return JSONResponse(ERROR_REGISTRY.serialize_exceptions(res))
    else:
        raise ExceptionRegistryNotFound(status_code=404, detail="Not Found")


@r.post('/register_exception', responses={400: {"model": ExceptionRegistryValidationError.response_model}})
def register_exception(request: Request, name: str, code: str,
                       description: str, category: ExceptionCategory) -> JSONResponse:
    try:
        res = ERROR_REGISTRY.register_error(name, code, description, category.value)
        return JSONResponse(ERROR_REGISTRY.serialize_exceptions([res]))
    except ValueError as e:
        raise ExceptionRegistryValidationError(status_code=400, detail=str(e))

@r.post('/delete_exception', responses={404: {"model": ExceptionRegistryNotFound.response_model}})
def delete_exception(request: Request, name: str, code: str) -> JSONResponse:
    res = ERROR_REGISTRY.delete_error(name, code)
    if res:
        return JSONResponse({"message": 'success'})
    else:
        raise ExceptionRegistryNotFound(status_code=404, detail="Not Found")