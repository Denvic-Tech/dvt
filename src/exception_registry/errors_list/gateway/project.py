from src.exception_registry.exception_types import ExceptionCategory
from src.exception_registry.registered_exception import RegisteredHTTPException


class ProjectVariableAlreadyExists(RegisteredHTTPException):
    name = "PROJECT_VARIABLE_ALREADY_EXISTS"
    code = "PROJECT_VARIABLE_409"
    description = "Project variable already exists"
    category = ExceptionCategory.SERVICE_GATEWAY_PROJECT.value


class ProjectVariableNotFound(RegisteredHTTPException):
    name = "PROJECT_VARIABLE_OT_FOUND"
    code = "PROJECT_VARIABLE_404"
    description = "Project variable not found"
    category = ExceptionCategory.SERVICE_GATEWAY_PROJECT.value


class ProjectAccessForbidden(RegisteredHTTPException):
    name = "PROJECT_ACCESS_FORBIDDEN"
    code = "PROJECT_ACCESS_403"
    description = "Project access forbidden"
    category = ExceptionCategory.SERVICE_GATEWAY_PROJECT.value


class ProjectNotFound(RegisteredHTTPException):
    name = "PROJECT_NOT_FOUND"
    code = "PROJECT_400"
    description = "Project not found"
    category = ExceptionCategory.SERVICE_GATEWAY_PROJECT.value


class DataFrameMetaNotFound(RegisteredHTTPException):
    name = "DATA_FRAME_META_NOT_FOUND"
    code = "DATA_FRAME_404"
    description = "DDFMeta not found"
    category = ExceptionCategory.SERVICE_GATEWAY_PROJECT.value


class DataFrameNotFound(RegisteredHTTPException):
    name = "DATA_FRAME_NOT_FOUND"
    code = "DATA_FRAME_404"
    description = "DataFrame not found"
    category = ExceptionCategory.SERVICE_GATEWAY_PROJECT.value


class JSONNotFound(RegisteredHTTPException):
    name = "JSON_NOT_FOUND"
    code = "JSON_404"
    description = "JSON not found"
    category = ExceptionCategory.SERVICE_GATEWAY_PROJECT.value
