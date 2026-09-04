import json
import logging
from collections.abc import Mapping
from enum import Enum, StrEnum
from typing import Annotated, Any, Dict, Literal, TypeAlias

import requests
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

from core.metadata import get_json_metadata

from src.exceptions import HTTPRequestBadRequest, HTTPRequestServiceUnavailable, HTTPRequestTimeout
from src.node_dsl import BaseNode, InputField, OutputField
from src.node_dsl.core.input_values import (
    NodeInputConstantValue,
    NodeInputExpressionValue,
    resolve_node_input_value,
)
from src.node_dsl.hooks import on_validation
from src.node_dsl.node_typing import IO
from src.node_dsl.types import NodeMetadata


class HTTPMethod(StrEnum):
    """HTTP методы"""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


class HTTPAuthType(StrEnum):
    """Способы авторизации HTTP запроса"""
    NONE = "none"
    BASIC = "basic"
    DIGEST = "digest"
    OAUTH2 = "oauth2"
    FILE_CERT = "file_cert"


type AuthStringValue = str | NodeInputExpressionValue | NodeInputConstantValue


def _validate_literal_auth_string(value: AuthStringValue, field_name: str) -> None:
    if isinstance(value, str) and not value:
        raise ValueError(f"Поле '{field_name}' не может быть пустым")


class HTTPNoAuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["none"] = "none"


class HTTPBasicAuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["basic"] = "basic"
    username: AuthStringValue
    password: AuthStringValue

    @model_validator(mode="after")
    def _validate_literals(self) -> "HTTPBasicAuthConfig":
        _validate_literal_auth_string(self.username, "username")
        _validate_literal_auth_string(self.password, "password")
        return self


class HTTPDigestAuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["digest"] = "digest"
    username: AuthStringValue
    password: AuthStringValue

    @model_validator(mode="after")
    def _validate_literals(self) -> "HTTPDigestAuthConfig":
        _validate_literal_auth_string(self.username, "username")
        _validate_literal_auth_string(self.password, "password")
        return self


class HTTPOAuth2Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["oauth2"] = "oauth2"
    token: AuthStringValue

    @model_validator(mode="after")
    def _validate_literals(self) -> "HTTPOAuth2Config":
        _validate_literal_auth_string(self.token, "token")
        return self


class HTTPFileCertAuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["file_cert"] = "file_cert"
    cert_file_path: AuthStringValue
    key_file_path: AuthStringValue | None = None
    key_password: AuthStringValue | None = None

    @model_validator(mode="after")
    def _validate_literals(self) -> "HTTPFileCertAuthConfig":
        _validate_literal_auth_string(self.cert_file_path, "cert_file_path")
        if self.key_file_path is not None:
            _validate_literal_auth_string(self.key_file_path, "key_file_path")
        if self.key_password:
            raise ValueError(
                "requests не поддерживает пароль приватного ключа через параметр cert. "
                "Используйте незашифрованный key_file_path или добавьте отдельную "
                "реализацию SSLContext/adapter."
            )
        return self


HTTPRequestAuthInput: TypeAlias = (
        HTTPNoAuthConfig
        | HTTPBasicAuthConfig
        | HTTPDigestAuthConfig
        | HTTPOAuth2Config
        | HTTPFileCertAuthConfig
)
HTTPRequestAuthConfig = Annotated[HTTPRequestAuthInput, Field(discriminator="type")]
_HTTP_AUTH_CONFIG_ADAPTER = TypeAdapter(HTTPRequestAuthConfig)


class HTTPRequest(BaseNode):
    TITLE = "HTTP Request"
    EMOJI = "🌐"
    CATEGORY = "API"
    DESCRIPTION = "Выполнение HTTP запросов"

    url: IO.STRING = InputField(
        description="URL для запроса"
    )

    method: HTTPMethod = InputField(
        default=HTTPMethod.GET,
        description="HTTP метод"
    )

    headers: IO.DICT = InputField(
        default={},
        description="HTTP заголовки в формате JSON"
    )

    params: IO.DICT = InputField(
        default={},
        description="Параметры запроса (query parameters) в формате JSON"
    )

    json_payload: dict[str, Any] | list[Any] | None = InputField(
        default=None,
        description="JSON тело запроса: объект или массив (для POST, PUT, PATCH)"
    )

    data: IO.DICT = InputField(
        default={},
        description="Form-encoded данные (для POST)"
    )

    timeout: IO.INT = InputField(
        default=30,
        min_value=1,
        max_value=300,
        description="Таймаут запроса в секундах"
    )

    verify_ssl: IO.BOOLEAN = InputField(
        default=True,
        description="Проверять SSL сертификаты"
    )

    auth: HTTPRequestAuthInput = InputField(
        default={"type": HTTPAuthType.NONE.value},
        description="Настройки авторизации HTTP запроса"
    )

    output: IO.JSON = OutputField(
        description="Результат HTTP запроса"
    )

    @on_validation
    def validate_request(self):
        """Валидация параметров запроса"""
        if not self.url:
            raise ValueError("URL не может быть пустым")

        self._validate_mapping_field("headers", self.headers)
        self._validate_mapping_field("params", self.params)
        self._validate_json_payload(self.json_payload)
        self._validate_mapping_field("data", self.data)
        self._parse_auth_config()

        # Для GET запросов не должно быть тела.
        if self.method == HTTPMethod.GET and (self.json_payload is not None or self.data):
            self.json_payload = None
            self.data = {}
            logging.warning("GET запросы не могут содержать тело (json_payload или data)")

    def _parse_auth_config(self) -> HTTPRequestAuthConfig:
        payload = {"type": HTTPAuthType.NONE.value} if self.auth is None else self.auth
        try:
            return _HTTP_AUTH_CONFIG_ADAPTER.validate_python(payload)
        except ValidationError as exc:
            raise ValueError(f"Некорректные настройки auth: {exc}") from exc

    def _project_variable_values(self) -> Dict[str, Any]:
        project_variables = self.project_variables
        return project_variables.raw_values if project_variables is not None else {}

    def _input_variable_values(self) -> Dict[str, Any]:
        return self.input_variables if isinstance(self.input_variables, dict) else {}

    def _resolve_auth_string(self, value: AuthStringValue, field_name: str) -> str:
        try:
            resolved_value = resolve_node_input_value(
                value,
                variables=self._input_variable_values(),
                project_variables=self._project_variable_values(),
                target_type=IO.STRING,
                allow_expressions=True,
                expression_policy="default",
                allow_unresolved=False,
            )
        except ValueError as err:
            raise ValueError(f"Не удалось вычислить auth.{field_name}: {err}") from err

        if not isinstance(resolved_value, str) or not resolved_value:
            raise ValueError(f"Поле 'auth.{field_name}' должно быть непустой строкой")
        return resolved_value

    def _resolve_optional_auth_string(
            self,
            value: AuthStringValue | None,
            field_name: str,
    ) -> str | None:
        if value is None:
            return None
        return self._resolve_auth_string(value, field_name)

    @staticmethod
    def _validate_mapping_field(field_name: str, field_value: Any) -> None:
        if field_value is not None and not isinstance(field_value, Mapping):
            raise ValueError(f"Поле '{field_name}' должно быть JSON объектом или None")

    @staticmethod
    def _validate_json_payload(field_value: Any) -> None:
        if field_value is not None and not isinstance(field_value, (Mapping, list, tuple)):
            raise ValueError("Поле 'json_payload' должно быть JSON объектом, массивом или None")

    @classmethod
    def _to_json_native(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {key: cls._to_json_native(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._to_json_native(item) for item in value]
        return value

    @classmethod
    def _normalize_mapping_field(cls, field_name: str, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Поле '{field_name}' содержит некорректный JSON") from exc
        if not isinstance(value, Mapping):
            raise ValueError(f"Поле '{field_name}' должно быть JSON объектом")
        return cls._to_json_native(value)

    @classmethod
    def _normalize_json_payload(cls, value: Any) -> dict[str, Any] | list[Any] | None:
        if value is None:
            return None
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError("Поле 'json_payload' содержит некорректный JSON") from exc
        normalized = cls._to_json_native(value)
        if not isinstance(normalized, (dict, list)):
            raise ValueError("Поле 'json_payload' должно быть JSON объектом или массивом")
        return normalized

    def _normalize_request_data(self) -> None:
        self.headers = self._normalize_mapping_field("headers", self.headers)
        self.params = self._normalize_mapping_field("params", self.params)
        self.json_payload = self._normalize_json_payload(self.json_payload)
        self.data = self._normalize_mapping_field("data", self.data)

        # Requests требует, чтобы заголовки были строго {str: str}.
        if self.headers:
            self.headers = {str(k): str(v) for k, v in self.headers.items()}

    def _apply_auth(self, request_kwargs: Dict[str, Any], headers: Dict[str, str]):
        auth_config = self._parse_auth_config()
        if isinstance(auth_config, HTTPNoAuthConfig):
            return

        if isinstance(auth_config, (HTTPBasicAuthConfig, HTTPDigestAuthConfig, HTTPOAuth2Config)):
            for header_name in list(headers):
                if header_name.lower() == "authorization":
                    headers.pop(header_name)

        if isinstance(auth_config, HTTPBasicAuthConfig):
            request_kwargs["auth"] = HTTPBasicAuth(
                self._resolve_auth_string(auth_config.username, "username"),
                self._resolve_auth_string(auth_config.password, "password"),
            )
        elif isinstance(auth_config, HTTPDigestAuthConfig):
            request_kwargs["auth"] = HTTPDigestAuth(
                self._resolve_auth_string(auth_config.username, "username"),
                self._resolve_auth_string(auth_config.password, "password"),
            )
        elif isinstance(auth_config, HTTPOAuth2Config):
            token = self._resolve_auth_string(auth_config.token, "token")
            headers["Authorization"] = f"Bearer {token}"
        elif isinstance(auth_config, HTTPFileCertAuthConfig):
            cert_file_path = self._resolve_auth_string(
                auth_config.cert_file_path,
                "cert_file_path",
            )
            key_file_path = self._resolve_optional_auth_string(
                auth_config.key_file_path,
                "key_file_path",
            )
            request_kwargs["cert"] = (
                (cert_file_path, key_file_path)
                if key_file_path
                else cert_file_path
            )

    def _prepare_args(self):
        self._normalize_request_data()
        # Подготавливаем параметры запроса
        request_kwargs = {
            'timeout': self.timeout,
            'verify': self.verify_ssl,
        }

        headers = dict(self.headers) if self.headers else {}
        self._apply_auth(request_kwargs, headers)

        # Добавляем заголовки, если они есть. Если auth_type != none, auth-настройки имеют
        # приоритет над вручную заданным Authorization.
        if headers:
            request_kwargs['headers'] = headers

        # Добавляем параметры запроса, если они есть
        if self.params:
            request_kwargs['params'] = self.params

        # Добавляем тело запроса в зависимости от метода
        if self.method in [HTTPMethod.POST, HTTPMethod.PUT, HTTPMethod.PATCH]:
            # Старые сохранённые form-data конфигурации используют пустой объект как
            # "json_payload не задан". Сохраняем этот fallback, но для обычного
            # JSON body разрешаем отправлять в том числе пустые {} и [].
            legacy_empty_json_with_form_data = self.json_payload == {} and bool(self.data)
            if self.json_payload is not None and not legacy_empty_json_with_form_data:
                request_kwargs['json'] = self.json_payload
            elif self.data:
                request_kwargs['data'] = self.data

        return request_kwargs

    def _make_request(self, request_kwargs):
        try:
            # Выполняем запрос
            response = requests.request(
                method=self.method,
                url=self.url,
                **request_kwargs
            )

            # Пробуем получить JSON ответ, если это возможно
            response.raise_for_status()
            result = response.json()
            self.output = result

        except requests.exceptions.Timeout as e:
            raise HTTPRequestTimeout(status_code=408, detail=str(e))
        except requests.exceptions.ConnectionError as e:
            raise HTTPRequestServiceUnavailable(status_code=503, detail=str(e))
        except requests.exceptions.RequestException as e:
            raise HTTPRequestBadRequest(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        return self.output

    def process(self) -> Dict[str, Any]:
        """Выполняет HTTP запрос и возвращает результат"""
        request_kwargs = self._prepare_args()
        self._make_request(request_kwargs)

        return self.output

    def infer_metadata(self) -> NodeMetadata:
        """ Определяет метаданные JSON из запроса """
        if self.output:
            return {"output": get_json_metadata(self.output)}
        else:
            request_kwargs = self._prepare_args()
            self._make_request(request_kwargs)

            return {"output": get_json_metadata(self.output)}
