from __future__ import annotations


def init_extensions(*args, **kwargs):
    from .loader import init_extensions as _init_extensions

    return _init_extensions(*args, **kwargs)


def import_extension_nodes(*args, **kwargs):
    from .loader import import_extension_nodes as _import_extension_nodes

    return _import_extension_nodes(*args, **kwargs)


def get_extension(*args, **kwargs):
    from .registry import get

    return get(*args, **kwargs)


def get_all_extensions(*args, **kwargs):
    from .registry import get_all

    return get_all(*args, **kwargs)


def load_extension_runtime(*args, **kwargs):
    from .runtime import load_extension_runtime as _load_extension_runtime

    return _load_extension_runtime(*args, **kwargs)


def load_all_extension_runtimes(*args, **kwargs):
    from .runtime import load_all_extension_runtimes as _load_all_extension_runtimes

    return _load_all_extension_runtimes(*args, **kwargs)


__all__ = [
    "get_all_extensions",
    "get_extension",
    "import_extension_nodes",
    "init_extensions",
    "load_all_extension_runtimes",
    "load_extension_runtime",
]
