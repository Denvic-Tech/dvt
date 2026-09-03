from __future__ import annotations

import abc
import types
from typing import Annotated, Any, ClassVar, Mapping, Sequence, Union, get_args, get_origin

from pydantic import BaseModel, TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src.setup.dsl.models import SetupFieldType, SetupStep, SetupStepField
from src.setup.exceptions import SetupValidationError


class BaseSetupStep(abc.ABC):
    CODE: ClassVar[str]
    ORDER: ClassVar[int] = 0
    TITLE: ClassVar[str]
    DESCRIPTION: ClassVar[str | None] = None
    SUBMIT_LABEL: ClassVar[str] = "Continue"

    @classmethod
    def sort_key(cls) -> tuple[int, str]:
        return cls.ORDER, cls.CODE

    @classmethod
    def validate_definition(cls) -> None:
        if not getattr(cls, "CODE", "").strip():
            raise ValueError(f"Setup step '{cls.__name__}' must define a non-empty CODE.")
        if not getattr(cls, "TITLE", "").strip():
            raise ValueError(f"Setup step '{cls.__name__}' must define a non-empty TITLE.")
        if not getattr(cls, "SUBMIT_LABEL", "").strip():
            raise ValueError(f"Setup step '{cls.__name__}' must define a non-empty SUBMIT_LABEL.")

    @classmethod
    async def get_status(cls, session: AsyncSession) -> SetupStep:
        completed = await cls.is_completed(session)
        fields = await cls.build_fields(session, completed=completed)
        return SetupStep(
            code=cls.CODE,
            title=cls.TITLE,
            description=cls.DESCRIPTION,
            submit_label=cls.SUBMIT_LABEL,
            completed=completed,
            fields=fields,
        )

    @classmethod
    def build_field(
        cls,
        *,
        key: str,
        label: str,
        field_type: SetupFieldType,
        required: bool,
        nullable: bool,
        value: str | int | float | bool | None = None,
    ) -> SetupStepField:
        return SetupStepField(
            key=key,
            label=label,
            type=field_type,
            required=required,
            nullable=nullable,
            value=value,
        )

    @classmethod
    def build_fields_from_model(
        cls,
        model_cls: type[BaseModel],
        *,
        include: Sequence[str] | None = None,
        values: Mapping[str, Any] | None = None,
        overrides: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> list[SetupStepField]:
        result: list[SetupStepField] = []
        keys = include or tuple(model_cls.model_fields.keys())

        for key in keys:
            field_info = model_cls.model_fields[key]
            field_overrides = dict((overrides or {}).get(key, {}))
            extra = field_info.json_schema_extra or {}
            field_type = field_overrides.get("type") or extra.get("setup_type")
            if field_type is None:
                field_type = cls.infer_field_type(key=key, annotation=field_info.annotation)

            nullable = field_overrides.get("nullable")
            if nullable is None:
                nullable = cls.is_nullable_annotation(field_info.annotation)

            required = field_overrides.get("required")
            if required is None:
                required = field_info.is_required()

            sensitive = field_overrides.get("sensitive")
            if sensitive is None:
                sensitive = bool(extra.get("sensitive")) or field_type == "password"

            value: str | int | float | bool | None = None
            if values is not None and key in values and not sensitive:
                value = cls.serialize_field_value(values[key])

            result.append(
                cls.build_field(
                    key=key,
                    label=field_overrides.get("label")
                    or extra.get("setup_label")
                    or field_info.title
                    or cls.humanize_key(key),
                    field_type=field_type,
                    required=required,
                    nullable=nullable,
                    value=value,
                )
            )

        return result

    @classmethod
    def validate_model(cls, model_cls: type[BaseModel], values: Mapping[str, Any]) -> BaseModel:
        try:
            return model_cls.model_validate(dict(values))
        except ValidationError as exc:
            raise SetupValidationError(cls.format_validation_error(exc)) from exc

    @classmethod
    def ensure_allowed_keys(cls, values: Mapping[str, Any], *, allowed_keys: Sequence[str]) -> None:
        allowed = set(allowed_keys)
        unknown_keys = sorted(key for key in values if key not in allowed)
        if unknown_keys:
            unknown_str = ", ".join(unknown_keys)
            raise SetupValidationError(f"Fields are not allowed during bootstrap: {unknown_str}.")

    @classmethod
    def validate_field_value(cls, *, key: str, annotation: Any, value: Any) -> Any:
        normalized_value = cls.normalize_optional_empty_string(annotation, value)
        try:
            return TypeAdapter(annotation).validate_python(normalized_value)
        except ValidationError as exc:
            raise SetupValidationError(f"{key}: {cls.format_validation_error(exc)}") from exc

    @staticmethod
    def format_validation_error(exc: ValidationError) -> str:
        messages: list[str] = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", ()) if part != "__root__")
            message = error.get("msg", "Invalid value.")
            messages.append(f"{location}: {message}" if location else message)
        return "; ".join(messages) if messages else str(exc)

    @staticmethod
    def humanize_key(key: str) -> str:
        return key.replace("_", " ").strip().title()

    @staticmethod
    def serialize_field_value(value: Any) -> str | int | float | bool | None:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    @staticmethod
    def normalize_optional_empty_string(annotation: Any, value: Any) -> Any:
        if value == "" and BaseSetupStep.is_nullable_annotation(annotation):
            return None
        return value

    @staticmethod
    def unwrap_annotated(annotation: Any) -> Any:
        if get_origin(annotation) is Annotated:
            args = get_args(annotation)
            if args:
                return args[0]
        return annotation

    @classmethod
    def strip_optional_annotation(cls, annotation: Any) -> tuple[Any, bool]:
        raw_annotation = cls.unwrap_annotated(annotation)
        origin = get_origin(raw_annotation)
        if origin is None:
            return raw_annotation, False

        args = get_args(raw_annotation)
        if origin in {Union, types.UnionType} and type(None) in args:
            non_none_args = tuple(arg for arg in args if arg is not type(None))
            if len(non_none_args) == 1:
                return cls.unwrap_annotated(non_none_args[0]), True
        return raw_annotation, False

    @classmethod
    def is_nullable_annotation(cls, annotation: Any) -> bool:
        _, nullable = cls.strip_optional_annotation(annotation)
        return nullable

    @classmethod
    def infer_field_type(cls, *, key: str, annotation: Any) -> SetupFieldType:
        normalized_annotation, _ = cls.strip_optional_annotation(annotation)
        key_lower = key.lower()

        if "password" in key_lower:
            return "password"
        if "email" in key_lower:
            return "email"
        if normalized_annotation is bool:
            return "boolean"
        if normalized_annotation in {int, float}:
            return "number"
        return "text"

    @classmethod
    @abc.abstractmethod
    async def is_completed(cls, session: AsyncSession) -> bool:
        raise NotImplementedError

    @classmethod
    @abc.abstractmethod
    async def build_fields(
        cls,
        session: AsyncSession,
        *,
        completed: bool,
    ) -> list[SetupStepField]:
        raise NotImplementedError

    @classmethod
    @abc.abstractmethod
    async def submit(cls, session: AsyncSession, values: Mapping[str, Any]) -> None:
        raise NotImplementedError
