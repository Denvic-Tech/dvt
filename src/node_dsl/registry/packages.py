import threading

from src.node_dsl.discovery.types import NodePackageDescriptor

from ._bootstrap import ensure_bootstrapped, registry_transaction, reset_bootstrap_state

NODE_PACKAGES: dict[str, NodePackageDescriptor] = {}

_REGISTRY_LOCK = threading.RLock()


def add(descriptor: NodePackageDescriptor) -> None:
    with registry_transaction(), _REGISTRY_LOCK:
        if descriptor.node_name in NODE_PACKAGES:
            raise ValueError(
                f"Node package descriptor for '{descriptor.node_name}' is already registered."
            )
        NODE_PACKAGES[descriptor.node_name] = descriptor


def get(node_name: str) -> NodePackageDescriptor:
    ensure_bootstrapped(is_ready=lambda: bool(NODE_PACKAGES))
    with registry_transaction(), _REGISTRY_LOCK:
        descriptor = NODE_PACKAGES.get(node_name)
    if descriptor is None:
        raise KeyError(f"Node package descriptor for '{node_name}' is not registered.")
    return descriptor


def get_all() -> dict[str, NodePackageDescriptor]:
    ensure_bootstrapped(is_ready=lambda: bool(NODE_PACKAGES))
    with registry_transaction(), _REGISTRY_LOCK:
        return NODE_PACKAGES.copy()


def clear() -> None:
    with registry_transaction(), _REGISTRY_LOCK:
        NODE_PACKAGES.clear()
    reset_bootstrap_state()
