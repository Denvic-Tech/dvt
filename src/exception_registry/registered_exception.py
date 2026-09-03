from http import HTTPStatus
from typing import Any, Optional, Dict

from fastapi import HTTPException, status
from pydantic import BaseModel, Field

from src.exception_registry.registry import ERROR_REGISTRY
from src.exception_registry.exception_types import ExceptionCategory, ExceptionType


class RegisteredExceptionMessage(BaseModel):
    name: str = Field(examples=['USER_NOT_FOUND'])
    code: str = Field(examples=['USER_001'])
    category: str = Field(examples=[ExceptionCategory.UNKNOWN.value])
    type: str = Field(examples=[ExceptionType.CUSTOM.value])

    # Динамическое
    description: str = Field(examples=['Пользователь не найден'])


class RegisteredException(Exception):
    """
    Базовый класс для всех регистрируемых исключений
    """
    # Эти атрибуты должны быть переопределены в дочерних классах
    name: str
    code: str
    category: str = ExceptionCategory.UNKNOWN.value
    type: str = ExceptionType.CUSTOM.value

    # Динамическое
    description: str

    exc_data: Any = None

    # Привязка к модели для responses
    response_model = RegisteredExceptionMessage

    @classmethod
    def serialize(cls):
        data = {
            'name': cls.name,
            'code': cls.code,
            'description': cls.description,
            'category': cls.category,
            'type': cls.type,
            'exc_data': cls.exc_data,
        }

        if cls.exc_data is not None:
            data['exc_data'] = cls.exc_data

        return data

    def __init__(self, description: Optional[str] = None):
        self.__class__.exc_data = description
        self.exc_data = description
        # Регистрируем только если класс полностью определен
        if (hasattr(self, 'name') and
                hasattr(self, 'code') and
                hasattr(self, 'description')):

            try:
                ERROR_REGISTRY.register_error(self)
            except ValueError:
                # Уже зарегистрировано - это нормально при переимпорте
                pass

    def __init_subclass__(cls, **kwargs):
        """Автоматически регистрируем исключение при создании класса"""
        super().__init_subclass__(**kwargs)

        # Регистрируем только если класс полностью определен
        if (hasattr(cls, 'name') and
                hasattr(cls, 'code') and
                hasattr(cls, 'description')):

            # Определяем response_model для FastAPI схемы
            class Model(BaseModel):
                name: str = Field(cls.name, examples=[cls.name])
                code: str = Field(cls.code, examples=[cls.code])
                description: str = Field(cls.description, examples=[cls.description])
                category: str = Field(cls.category, examples=[cls.category])
                type: str = Field(cls.type, examples=[cls.type])

            Model.__name__ = cls.__name__
            Model.__qualname__ = cls.__qualname__
            cls.response_model = Model

            try:
                ERROR_REGISTRY.register_error(cls)
            except ValueError:
                # Уже зарегистрировано - это нормально при переимпорте
                pass

    @classmethod
    def update_response_model(cls, **kwargs):
        for k, v in kwargs.items():
            setattr(cls.response_model, k, v)

    def __hash__(self) -> int:
        if isinstance(self.description, dict) or isinstance(self.exc_data, dict):
            if isinstance(self.description, dict):
                description_hash = hash(self.description.values())
            else:
                description_hash = hash(self.description)
            if isinstance(self.exc_data, dict):
                exc_data_hash = hash(self.exc_data.values())
            else:
                exc_data_hash = hash(self.exc_data)
            return hash((self.name, self.code, self.category)) + description_hash + exc_data_hash
        else:
            return hash((self.name, self.code, self.description, self.category, self.exc_data))

    def __reduce__(self):
        return self.__class__, (self.name, self.code, self.description, self.category, self.exc_data)


class RegisteredHTTPException(RegisteredException, HTTPException):
    type: str = ExceptionType.HTTP_GENERATED.value
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    detail: Optional[str] = None

    def __init__(self, status_code: HTTPStatus | int = None, detail: Any = None, headers: Optional[Dict[str, str]] = None):
        self.exc_data = detail

        if status_code is not None:
            self.status_code = status_code

        if self.detail is None and self.description:
            self.detail = self.description

        if detail is not None:
            self.detail = detail

        HTTPException.__init__(self, self.status_code, self.detail, headers)
        RegisteredException.__init__(self, detail)
