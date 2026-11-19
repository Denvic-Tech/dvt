import json
from types import SimpleNamespace

import pytest

from services.installation_manager.infrastructure import application_host
from services.installation_manager.infrastructure.application_host import (
    ApplyError,
    ComposeApplicationHost,
)

DIGEST = "sha256:" + "1" * 64
OTHER_DIGEST = "sha256:" + "2" * 64
LOCAL_MANAGER = f"dvt/installation_manager@{DIGEST}"
REGISTRY_MANAGER = f"cr.distribution.denvic.tech/dvt/installation_manager@{DIGEST}"
TARGET_MANAGER = f"cr.distribution.denvic.tech/dvt/installation_manager@{OTHER_DIGEST}"


@pytest.mark.parametrize(
    ("source", "repo_digest", "accepted"),
    [
        (LOCAL_MANAGER, "docker.io/" + LOCAL_MANAGER, True),
        (REGISTRY_MANAGER, REGISTRY_MANAGER, True),
        (LOCAL_MANAGER, f"docker.io/dvt/installation_manager@{OTHER_DIGEST}", False),
        (LOCAL_MANAGER, f"docker.io/other/installation_manager@{DIGEST}", False),
    ],
)
def test_observed_manager_matches_repository_and_digest(
    monkeypatch, tmp_path, source, repo_digest, accepted,
):
    running = {
        "Image": "running-image-id",
        "Config": {
            "Labels": {
                "com.docker.compose.project": "dvt",
                "com.docker.compose.service": "installation_manager",
                "com.docker.compose.oneoff": "False",
            },
        },
    }

    def docker(command, action, *_args, **_kwargs):
        payload = {
            ("container", "ls"): "manager-container-id",
            ("container", "inspect"): json.dumps([running]),
            ("image", "inspect"): json.dumps([{"RepoDigests": [repo_digest]}]),
        }[command, action]
        return SimpleNamespace(stdout=payload)

    monkeypatch.setattr(application_host, "docker", docker)
    monkeypatch.setattr(application_host, "StagingDocker", lambda *_: SimpleNamespace())
    host = ComposeApplicationHost(
        {"project": "dvt", "manager": source, "candidate": TARGET_MANAGER},
        tmp_path,
        {"services": {"installation_manager": {}}},
        {
            "platform": "linux/amd64",
            "services": {"installation_manager": TARGET_MANAGER},
            "observed_images": {"installation_manager": source},
        },
        None,
    )

    if accepted:
        assert host.containers() == {"installation_manager": [running]}
    else:
        with pytest.raises(ApplyError, match="outside the staged images"):
            host.containers()
