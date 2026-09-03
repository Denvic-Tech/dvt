import abc
import copy
from typing import Dict, Tuple, Any, Callable, overload, get_type_hints
from typing import TYPE_CHECKING

from src.node_dsl.type_resolver import TypeResolver
from src.node_dsl.field import InputField, OutputField, FieldBase
from src.logger import logger

if TYPE_CHECKING:
    from src.node_dsl import BaseNode


type_resolver = TypeResolver()


@overload
def _clone_field(field: InputField) -> InputField: ...

@overload
def _clone_field(field: OutputField) -> OutputField: ...

def _clone_field(field: FieldBase) -> FieldBase:
    """
    Field instances are mutable: type resolving populates resolved_type/options/etc.
    When a field is inherited (e.g. BaseNode.input_variables),
    we must not share the same object across subclasses to avoid cross-class mutation.
    """
    return copy.deepcopy(field)


def _resolve_annotations_for_runtime_class(cls: type) -> Dict[str, Any]:
    try:
        return get_type_hints(cls, include_extras=True)
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Falling back to raw __annotations__ for '{}' because get_type_hints failed: {}",
            cls.__name__,
            exc,
        )
        return dict(getattr(cls, "__annotations__", {}) or {})


def _merge_inherited_fields(
        *,
        bases: Tuple[type, ...],
        disabled_outputs: set[str],
        include_node_fields: bool,
        include_mixin_fields: bool,
) -> tuple[Dict[str, InputField], Dict[str, OutputField]]:
    input_fields: Dict[str, InputField] = {}
    output_fields: Dict[str, OutputField] = {}

    for base in reversed(bases):
        if include_node_fields:
            base_inputs = getattr(base, "_input_field_instances", None) or {}
            for attr_name, field in base_inputs.items():
                input_fields[attr_name] = _clone_field(field)

            base_outputs = getattr(base, "_output_field_instances", None) or {}
            for attr_name, field in base_outputs.items():
                if attr_name in disabled_outputs:
                    continue
                output_fields[attr_name] = _clone_field(field)

        if include_mixin_fields:
            mixin_inputs = getattr(base, "_mixin_input_field_instances", None) or {}
            for attr_name, field in mixin_inputs.items():
                input_fields[attr_name] = _clone_field(field)

            mixin_outputs = getattr(base, "_mixin_output_field_instances", None) or {}
            for attr_name, field in mixin_outputs.items():
                if attr_name in disabled_outputs:
                    continue
                output_fields[attr_name] = _clone_field(field)

    return input_fields, output_fields


def _collect_declared_fields(
        *,
        owner_name: str,
        current_attrs: Dict[str, Any],
        annotations: Dict[str, Any],
        input_fields: Dict[str, InputField],
        output_fields: Dict[str, OutputField],
) -> tuple[Dict[str, InputField], Dict[str, OutputField]]:
    for attr_name, attr_value in current_attrs.items():
        if not isinstance(attr_value, FieldBase):
            continue

        field_instance = attr_value
        field_instance.attr_name = attr_name

        py_type = annotations.get(attr_name)
        if py_type is None:
            logger.warning(f"Missing type annotation for field Name={attr_name} in node Name={owner_name}")

            if isinstance(field_instance, InputField) and field_instance.default is not ...:
                py_type = type(field_instance.default)
            else:
                py_type = Any

        try:
            resolved_type = type_resolver.resolve(py_type)
        except ValueError as exc:
            logger.error(f"Invalid type annotation for field Name={attr_name} in node Name={owner_name}: {exc}")
            raise

        field_instance.assigned_type = py_type
        field_instance.resolved_type = resolved_type.io_type
        field_instance.is_list_type = resolved_type.is_list_type

        if isinstance(field_instance, InputField):
            field_instance.is_literal_type = resolved_type.is_literal_type
            field_instance.options = resolved_type.options

            if resolved_type.schema:
                field_instance.schema = resolved_type.schema

            field_instance.optional = resolved_type.is_optional

            if field_instance.optional and field_instance.default is Ellipsis:
                field_instance.default = None

            input_fields[attr_name] = field_instance
            continue

        output_fields[attr_name] = field_instance

    return input_fields, output_fields


def collect_mixin_fields(mixin_cls: type) -> tuple[Dict[str, InputField], Dict[str, OutputField]]:
    input_fields, output_fields = _merge_inherited_fields(
        bases=mixin_cls.__bases__,
        disabled_outputs=set(),
        include_node_fields=False,
        include_mixin_fields=True,
    )
    return _collect_declared_fields(
        owner_name=mixin_cls.__name__,
        current_attrs=dict(vars(mixin_cls)),
        annotations=_resolve_annotations_for_runtime_class(mixin_cls),
        input_fields=input_fields,
        output_fields=output_fields,
    )


class BaseNodeMeta(abc.ABCMeta):
    """
    Метакласс для BaseNode.
    Создает Pydantic модель на основе аннотаций и дескрипторов InputField/OutputField.
    Собирает метаданные для определения ноды.
    """

    def __new__(cls, name: str, bases: Tuple[type, ...], dct: Dict[str, Any]):
        # Collect fields for every node class, including BaseNode itself.
        # This allows "global" inputs defined on BaseNode to be:
        # - present in definitions (UI),
        # - initialized as plain attributes on subclasses (not as InputField descriptors),
        # - safely overrideable per-node.
        dct = cls._process_fields(name, bases, dct)
        dct = cls._set_defaults(dct)
        dct = cls._set_meta_cache_key(dct)

        return type.__new__(cls, name, bases, dct)

    @staticmethod
    def _process_fields(name: str, bases: Tuple[type, ...], dct: Dict[str, Any]):
        annotations = dct.get("__annotations__", {})

        disabled_outputs = set(dct.get("DISABLED_OUTPUTS") or [])
        if disabled_outputs:
            logger.debug(f"Node '{name}' disabled outputs: {disabled_outputs}")

        input_fields, output_fields = _merge_inherited_fields(
            bases=bases,
            disabled_outputs=disabled_outputs,
            include_node_fields=True,
            include_mixin_fields=True,
        )
        input_fields, output_fields = _collect_declared_fields(
            owner_name=name,
            current_attrs=dict(dct),
            annotations=annotations,
            input_fields=input_fields,
            output_fields=output_fields,
        )

        dct['_input_field_instances'] = input_fields
        dct['_output_field_instances'] = output_fields

        return dct

    @staticmethod
    def _set_defaults(dct: Dict[str, Any]):
        input_fields: Dict[str, InputField] | None = dct.get('_input_field_instances', {})
        output_fields: Dict[str, OutputField] | None = dct.get('_output_field_instances', {})

        for attr_name, field_instance in input_fields.items():
            if isinstance(field_instance, InputField):
                dct[attr_name] = field_instance.default

        for attr_name, field_instance in output_fields.items():
            if isinstance(field_instance, OutputField):
                dct[attr_name] = Ellipsis

        return dct

    @staticmethod
    def _set_meta_cache_key(dct: Dict[str, Any]):

        orig_method: Callable[["BaseNode"], str | None] | None = dct.get('get_metadata_cache_key', None)

        if not orig_method:
            return dct

        dct['_meta_cache_key'] = None

        def wrapper(__node_self: "BaseNode") -> str:
            if __node_self._meta_cache_key is None:
                __node_self._meta_cache_key = orig_method(__node_self)
            return __node_self._meta_cache_key

        dct['get_metadata_cache_key'] = wrapper

        return dct
