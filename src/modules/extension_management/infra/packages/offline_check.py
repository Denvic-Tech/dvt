"""Verify the declared offline wheels with the target image's Python and ABI."""

import subprocess
import sys
from pathlib import Path

from ..runtime.loader import check_dvt_compatibility, load_manifest
from .dependencies import build_extension_pip_install_command, extension_pip_environment


def check(root: Path) -> None:
    for directory in sorted(root.iterdir()):
        manifest = load_manifest(directory, extension_name=directory.name)
        if manifest is None or not check_dvt_compatibility(manifest):
            raise ValueError("The offline extension manifest is incompatible")
        if manifest.requirements:
            command = build_extension_pip_install_command(
                manifest.requirements, install_root=directory, offline_only=True
            )
            command[4:4] = ["--dry-run", "--ignore-installed"]
            subprocess.run(
                command, stdin=subprocess.DEVNULL, check=True, timeout=180,
                env=extension_pip_environment(),
            )


if __name__ == "__main__":
    check(Path(sys.argv[1]))
