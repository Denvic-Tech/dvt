from __future__ import annotations


def add_node(*args, **kwargs):
    from .nodes import add

    return add(*args, **kwargs)


def get_node(*args, **kwargs):
    from .nodes import get

    return get(*args, **kwargs)


def get_all_nodes(*args, **kwargs):
    from .nodes import get_all

    return get_all(*args, **kwargs)


def add_node_package(*args, **kwargs):
    from .packages import add

    return add(*args, **kwargs)


def get_node_package(*args, **kwargs):
    from .packages import get

    return get(*args, **kwargs)


def get_all_node_packages(*args, **kwargs):
    from .packages import get_all

    return get_all(*args, **kwargs)


def add_definition(*args, **kwargs):
    from .definitions import add

    return add(*args, **kwargs)


def build_definition(*args, **kwargs):
    from .definitions import build

    return build(*args, **kwargs)


def get_definition(*args, **kwargs):
    from .definitions import get

    return get(*args, **kwargs)


def get_all_definitions(*args, **kwargs):
    from .definitions import get_all

    return get_all(*args, **kwargs)


def add_hook(*args, **kwargs):
    from .hooks import add

    return add(*args, **kwargs)


def build_hooks(*args, **kwargs):
    from .hooks import build

    return build(*args, **kwargs)


def get_hooks(*args, **kwargs):
    from .hooks import get

    return get(*args, **kwargs)


def get_all_hooks(*args, **kwargs):
    from .hooks import get_all

    return get_all(*args, **kwargs)


def run_hooks(*args, **kwargs):
    from .hooks import run

    return run(*args, **kwargs)


async def run_hooks_async(*args, **kwargs):
    from .hooks import run_async

    return await run_async(*args, **kwargs)


__all__ = [
    "add_definition",
    "add_hook",
    "add_node",
    "add_node_package",
    "build_definition",
    "build_hooks",
    "get_all_definitions",
    "get_all_hooks",
    "get_all_node_packages",
    "get_all_nodes",
    "get_definition",
    "get_hooks",
    "get_node",
    "get_node_package",
    "run_hooks",
    "run_hooks_async",
]
