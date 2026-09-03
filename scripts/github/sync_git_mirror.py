from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path


def run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(list(args), cwd=cwd, check=True)


def sync_mirror(source_url: str, target_url: str) -> None:
    with tempfile.TemporaryDirectory(prefix="dvt-git-mirror-") as tmp:
        repo = Path(tmp) / "mirror.git"
        run("git", "init", "--bare", "--quiet", str(repo))
        run("git", "remote", "add", "source", source_url, cwd=repo)
        run("git", "remote", "add", "target", target_url, cwd=repo)
        run(
            "git",
            "fetch",
            "--quiet",
            "--force",
            "--prune",
            "source",
            "+refs/heads/*:refs/heads/*",
            "+refs/tags/*:refs/tags/*",
            cwd=repo,
        )
        run("git", "push", "--quiet", "--force", "--prune", "target", "refs/heads/*:refs/heads/*", cwd=repo)
        run("git", "push", "--quiet", "--force", "--prune", "target", "refs/tags/*:refs/tags/*", cwd=repo)


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize Git heads and tags into an exact mirror.")
    parser.add_argument("source_url")
    parser.add_argument("target_url")
    args = parser.parse_args()
    sync_mirror(args.source_url, args.target_url)
    print("Mirror synchronized: heads and tags only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
