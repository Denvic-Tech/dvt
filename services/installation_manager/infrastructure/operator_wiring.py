"""Attach the Gateway to the protected manager without sharing operator credentials."""

from pathlib import Path

from ..candidate_auth import CandidateAuth
from ..host_bootstrap import CONTROL
from .staging_artifacts import write_artifact

CA_TARGET = "/run/dvt-operator/ca.pem"
TOKEN_TARGET = "/run/dvt-operator/gateway-token"


def operator_binds(data: str, *, http: bool = False) -> dict[str, str]:
    control = Path(data) / CONTROL
    paths = {TOKEN_TARGET: str(control / "gateway-token")}
    if not http:
        paths[CA_TARGET] = str(control / "ca.pem")
    return paths


def wire_gateway(services: dict, config: dict) -> None:
    """Add trusted runtime wiring after the signed service model has been checked."""
    auth = CandidateAuth(config)
    paths = operator_binds(config["data"], http=config.get("manager_http") is True)
    write_artifact(Path(paths[TOKEN_TARGET]), auth.gateway_token.encode("ascii"))
    gateway = services["gateway"]
    manager = services["installation_manager"]
    gateway["networks"].update(
        {name: None for name in manager["networks"] if name not in gateway["networks"]}
    )
    gateway["volumes"].extend({
        "type": "bind", "source": source, "target": target,
        "read_only": True, "bind": {"create_host_path": False},
    } for target, source in paths.items())
    gateway["environment"]["DVT_OPERATOR_MANAGER_ORIGIN"] = auth.origin
