from inspect import Parameter, Signature
from dataclasses import is_dataclass, fields, MISSING
from typing import get_type_hints, Any, Annotated
from fastapi import Body


def make_signature_from_dataclass(dc_type: type) -> Signature:
    if not is_dataclass(dc_type):
        raise TypeError("Ожидался dataclass")

    hints = get_type_hints(dc_type, include_extras=True)
    params: list[Parameter] = []

    for f in fields(dc_type):
        if not f.init:
            continue

        anno = Annotated[hints.get(f.name, Any), Body()]
        default = f.default if f.default is not MISSING else Parameter.empty

        params.append(Parameter(
            name=f.name,
            kind=Parameter.KEYWORD_ONLY,
            default=default,
            annotation=anno,
        ))

    return Signature(parameters=params)
