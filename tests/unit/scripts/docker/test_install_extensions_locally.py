from __future__ import annotations

from pathlib import Path

import pytest
from scripts.docker import install_extensions_locally


def test_strict_mode_fails_when_extension_installation_fails(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        install_extensions_locally,
        "fetch_extension_list",
        lambda *_args, **_kwargs: [
            {
                "name": "sample-extension",
                "latest_compatible_version": "1.0.0",
            }
        ],
    )
    monkeypatch.setattr(
        install_extensions_locally,
        "resolve_download_url",
        lambda *_args, **_kwargs: "https://example.invalid/sample-extension.zip",
    )

    def fail_install(*_args, **_kwargs) -> None:
        raise RuntimeError("broken package")

    monkeypatch.setattr(install_extensions_locally, "install_one", fail_install)

    with pytest.raises(SystemExit) as exc_info:
        install_extensions_locally.run(
            [
                "--target-dir",
                str(tmp_path),
                "--strict",
            ]
        )

    assert exc_info.value.code == 1


def test_non_strict_mode_preserves_best_effort_behavior(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        install_extensions_locally,
        "fetch_extension_list",
        lambda *_args, **_kwargs: [
            {
                "name": "sample-extension",
                "latest_compatible_version": "1.0.0",
            }
        ],
    )
    monkeypatch.setattr(
        install_extensions_locally,
        "resolve_download_url",
        lambda *_args, **_kwargs: None,
    )

    install_extensions_locally.run(["--target-dir", str(tmp_path)])
