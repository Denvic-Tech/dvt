from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
MIRROR_PATH = REPO_ROOT / "scripts" / "github" / "sync_git_mirror.py"
CLASSIFIER_PATH = REPO_ROOT / "scripts" / "github" / "classify_ci_event.py"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git executable is required")


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str, capture: bool = False) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
    )
    return (result.stdout or "").strip()


def commit(repo: Path, name: str, content: str) -> str:
    (repo / name).write_text(content, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-m", content.strip())
    return git(repo, "rev-parse", "HEAD", capture=True)


def refs(repo: Path) -> set[str]:
    text = git(repo, "for-each-ref", "--format=%(refname)", capture=True)
    return set(text.splitlines()) if text else set()


def test_mirror_sync_handles_updates_force_push_deletions_and_ignores_other_refs(tmp_path: Path) -> None:
    mirror = load_module(MIRROR_PATH, "sync_git_mirror")
    source = tmp_path / "source"
    target = tmp_path / "target.git"
    source.mkdir()
    git(source, "init", "-b", "main")
    git(source, "config", "user.email", "ci@example.com")
    git(source, "config", "user.name", "CI")
    first = commit(source, "a.txt", "one\n")
    git(source, "branch", "dev")
    git(source, "tag", "1.0.0")
    git(source, "update-ref", "refs/pull/1/head", first)
    subprocess.run(["git", "init", "--bare", str(target)], check=True, stdout=subprocess.DEVNULL)

    mirror.sync_mirror(str(source), str(target))
    assert {"refs/heads/main", "refs/heads/dev", "refs/tags/1.0.0"} <= refs(target)
    assert "refs/pull/1/head" not in refs(target)

    git(source, "switch", "dev")
    second = commit(source, "b.txt", "two\n")
    git(source, "tag", "1.1.0")
    mirror.sync_mirror(str(source), str(target))
    assert git(target, "rev-parse", "refs/heads/dev", capture=True) == second
    assert "refs/tags/1.1.0" in refs(target)

    git(source, "reset", "--hard", first)
    forced = commit(source, "c.txt", "forced\n")
    git(source, "tag", "-f", "1.1.0", forced)
    mirror.sync_mirror(str(source), str(target))
    assert git(target, "rev-parse", "refs/heads/dev", capture=True) == forced
    assert git(target, "rev-parse", "refs/tags/1.1.0", capture=True) == forced

    git(source, "switch", "main")
    git(source, "branch", "-D", "dev")
    git(source, "tag", "-d", "1.0.0")
    mirror.sync_mirror(str(source), str(target))
    assert "refs/heads/dev" not in refs(target)
    assert "refs/tags/1.0.0" not in refs(target)

    before = refs(target)
    mirror.sync_mirror(str(source), str(target))
    assert refs(target) == before


def test_trigger_classification_contract() -> None:
    classifier = load_module(CLASSIFIER_PATH, "classify_ci_event")
    cases = {
        ("push", "refs/heads/dev"): (True, "dev", ""),
        ("push", "refs/heads/dev-alice"): (False, "", ""),
        ("push", "refs/heads/main"): (False, "", ""),
        ("push", "refs/tags/1.24.0-rc1"): (True, "rc", "1.24.0-rc1"),
        ("push", "refs/tags/1.24.0"): (True, "release", "1.24.0"),
        ("push", "refs/tags/1.24.0rc1"): (False, "", ""),
        ("push", "refs/tags/not-a-release"): (False, "", ""),
        ("delete", "refs/tags/1.24.0"): (False, "", ""),
        ("delete", "refs/heads/dev"): (False, "", ""),
        ("workflow_dispatch", "refs/heads/main"): (False, "", ""),
    }
    for (event_name, ref), expected in cases.items():
        result = classifier.classify(event_name, ref)
        assert (result.should_trigger, result.event_kind, result.release_tag) == expected
