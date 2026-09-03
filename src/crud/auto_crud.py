import inspect

from typing import Any
from typing import Dict
from typing import List
from typing import Union
from typing import Tuple
from typing import Optional
from typing import Callable
from typing import Annotated
from typing import ForwardRef
from typing import Type, TypeVar
from typing import get_origin, get_args

from sqlmodel import SQLModel
from sqlmodel.main import FieldInfo, SQLModelMetaclass

from pydantic import BaseModel, Field, create_model
from pydantic.fields import FieldInfo as PydanticFieldInfo
from pydantic._internal._model_construction import ModelMetaclass

from sqlalchemy.orm.attributes import InstrumentedAttribute


ModelT = TypeVar('ModelT', bound=BaseModel)
IncludeFieldType = Union[
    str,                        # str, ex. "TaskRead"
    Annotated[Any, FieldInfo],  # annotated, ex. (Annotated["TaskRead", Field(alias="task")])
    Tuple[Type, FieldInfo],     # tuple, ex. (TaskRead, Field(alias="task"))
    Type                        # just type, ex. TaskRead
]
IncludeFieldsType = Dict[str, IncludeFieldType]


CREATE_SCHEMA_EXCLUDE_FIELDS = [
    "id",
]

READ_SCHEMA_EXCLUDE_FIELDS = [
    "password",
]


def _to_exclude(
        field_name: str,
        exclude_fields: List[Union[str, InstrumentedAttribute]]
):
    for exclude_field in exclude_fields:
        exclude_field: Union[str, InstrumentedAttribute]
        if isinstance(exclude_field, str) and field_name == exclude_field:
            return True

        if isinstance(exclude_field, InstrumentedAttribute) and field_name == exclude_field.key:
            return True

    return False


def _parse_field_definition(field_definition: Any) -> Tuple[Any, FieldInfo]:
    # 1) Если кортеж вида (тип, Field):
    if isinstance(field_definition, tuple):
        if len(field_definition) != 2:
            raise ValueError("Tuple for include_fields must have length 2: (Type, FieldInfo).")
        field_type, field_info = field_definition
        field_info: FieldInfo

        if isinstance(field_type, str):
            field_type = ForwardRef(field_type)

        if not isinstance(field_info, (FieldInfo, PydanticFieldInfo)):
            raise TypeError("Second element of tuple for include_fields must be FieldInfo (Field(...)).")

        field_info.annotation = field_type

        return field_type, field_info

    # 2) Если строка делаем ForwardRef:
    if isinstance(field_definition, str):
        field_type = ForwardRef(field_definition)
        return field_type, FieldInfo(annotation=field_type)

    # 3) Проверка на Annotated
    origin = get_origin(field_definition)
    if origin is not None and origin is Annotated:
        args = get_args(field_definition)
        if not args:
            raise ValueError("Annotated(...) without arguments is not allowed.")
        field_type = args[0]
        # Ищем FieldInfo среди оставшихся
        field_info: Optional[FieldInfo] = None
        for arg in args[1:]:
            if isinstance(arg, FieldInfo):
                field_info = arg
                break

        if field_info is None:
            field_info = FieldInfo()

        if isinstance(field_type, str):
            field_type = ForwardRef(field_type)

        field_info.annotation = field_type

        return field_type, field_info

    # 4) Если просто тип
    if isinstance(field_definition, type):
        return field_definition, FieldInfo(annotation=field_definition)

    # 5) Че то неизвестное
    raise TypeError(f"Unexpected include_fields type: {field_definition!r}")


def _clone_field_info_with_default(field_info: FieldInfo, default: Any) -> FieldInfo:
    """
    Создаёт копию FieldInfo с переопределённым default,
    сбрасывая default_factory, чтобы избежать конфликтов Pydantic.
    """

    attributes = dict(field_info._attributes_set)
    attributes.pop("default_factory", None)
    attributes["default"] = default

    cloned_field_info = type(field_info)(**attributes)
    cloned_field_info.annotation = field_info.annotation

    return cloned_field_info


def rebuild_models(models: List[Type[ModelT]]):
    for model in models:
        model.__module__ = "src.models"
        model.model_rebuild()

    return models


def rebuild_all_models(_locals: Dict[str, Any]):
    for class_name, model_class in _locals.items():
        if isinstance(model_class, ModelMetaclass):
            model_class.model_rebuild(_types_namespace=_locals)


def generate_create_schema(
        base_name: str,
        fields: Dict[str, Tuple[Type, FieldInfo]],

        include_fields: Optional[Dict[str, Tuple[Type, FieldInfo]]] = None,
        exclude_fields: Optional[List[Union[str, InstrumentedAttribute]]] = None
) -> Type[ModelT]:
    """
    Auto generate CreateSchema from fields
    """

    include_fields = include_fields if include_fields is not None else {}
    exclude_fields = CREATE_SCHEMA_EXCLUDE_FIELDS + (exclude_fields if exclude_fields is not None else [])

    create_fields = {
        field_name: (field_type, field_info)
        for field_name, (field_type, field_info) in fields.items()
        if not _to_exclude(field_name, exclude_fields)
    }

    for field_name, field_type in include_fields.items():
        ...
        # Реализуй добавление дополнительных полей

    return create_model(
        f"{base_name}Create",
        **create_fields
    )


def generate_read_schema(
        base_name: str,
        fields: Dict[str, Tuple[Type, FieldInfo]],

        include_fields: Optional[IncludeFieldsType] = None,
        exclude_fields: Optional[List[InstrumentedAttribute]] = None
) -> Type[ModelT]:
    """
    Auto generate ReadSchema from fields
    """

    include_fields = include_fields if include_fields is not None else {}
    exclude_fields = READ_SCHEMA_EXCLUDE_FIELDS + (exclude_fields if exclude_fields is not None else [])

    read_fields = {
        field_name: (field_type, field_info)
        for field_name, (field_type, field_info) in fields.items()
        if not _to_exclude(field_name, exclude_fields)
    }

    for field_name, field_definition in include_fields.items():
        the_type, the_field_info = _parse_field_definition(field_definition)
        read_fields[field_name] = (the_type, the_field_info)

    model = create_model(
        f"{base_name}Read",
        **read_fields
    )

    return model


def generate_update_schema(
        base_name: str,
        fields: Dict[str, Tuple[Type, FieldInfo]],

        include_fields: Optional[IncludeFieldsType] = None,
        exclude_fields: Optional[List[InstrumentedAttribute]] = None
) -> Type[ModelT]:
    """
    Auto generate UpdateSchema from fields
    """

    include_fields = include_fields if include_fields is not None else {}
    exclude_fields = exclude_fields if exclude_fields is not None else []

    update_fields = {}
    for field_name, (field_type, field_info) in fields.items():
        if _to_exclude(field_name, exclude_fields):
            continue
        cloned_field_info = _clone_field_info_with_default(field_info, default=None)
        update_fields[field_name] = (field_type, cloned_field_info)

    for field_name, field_type in include_fields.items():
        ...
        # Реализуй добавление дополнительных полей

    return create_model(
        f"{base_name}Update",
        **update_fields
    )


def generate_crud_schemas(
        table_cls: Type[ModelT],

        include_to_read: Optional[IncludeFieldsType] = None,
        include_to_update: Optional[IncludeFieldsType] = None,
        include_to_create: Optional[IncludeFieldsType] = None,

        exclude_from_create: Optional[List[InstrumentedAttribute]] = None,
        exclude_from_read: Optional[List[InstrumentedAttribute]] = None,
        exclude_from_update: Optional[List[InstrumentedAttribute]] = None,

        include_callables: Optional[List[Callable]] = None
) -> Tuple[Type[ModelT], Type[ModelT], Type[ModelT]]:
    """
    Auto generate CRUD schemas from SQLModel's subclass
    :param table_cls: SQLModel's subclass

    :param include_to_read: Include fields to ReadSchema
    :param include_to_update: Include fields to UpdateSchema
    :param include_to_create: Include fields to CreateSchema

    :param exclude_from_create: Exclude fields from CreateSchema
    :param exclude_from_read: Exclude fields from ReadSchema
    :param exclude_from_update: Exclude fields from UpdateSchema

    :return: CreateSchema, ReadSchema, UpdateSchema
    """
    table_cls: SQLModel

    base_name = table_cls.__name__.replace("Base", "")

    all_fields = {}
    for field_name, field_info in table_cls.model_fields.items():
        field_type = field_info.annotation

        all_fields[field_name] = (field_type, field_info)

    CreateSchema = generate_create_schema(
        base_name=base_name,
        fields=all_fields,

        include_fields=include_to_create,
        exclude_fields=exclude_from_create
    )

    ReadSchema = generate_read_schema(
        base_name=base_name,
        fields=all_fields,

        include_fields=include_to_read,
        exclude_fields=exclude_from_read
    )

    UpdateSchema = generate_update_schema(
        base_name=base_name,
        fields=all_fields,

        include_fields=include_to_update,
        exclude_fields=exclude_from_update
    )

    if include_callables is not None:
        for fn in include_callables:
            if inspect.iscoroutinefunction(fn):
                attach_async_method(CreateSchema, fn)
                attach_async_method(ReadSchema, fn)
                attach_async_method(UpdateSchema, fn)
            else:
                attach_sync_method(CreateSchema, fn)
                attach_sync_method(ReadSchema, fn)
                attach_sync_method(UpdateSchema, fn)

    return CreateSchema, ReadSchema, UpdateSchema


def attach_async_method(cls, fn: Callable):
    async def method(self, *args, **kwargs):
        return await fn(self, *args, **kwargs)

    method.__name__ = fn.__name__
    method.__doc__ = fn.__doc__

    setattr(cls, fn.__name__, method)


def attach_sync_method(cls, fn: Callable):
    setattr(cls, fn.__name__, fn)
