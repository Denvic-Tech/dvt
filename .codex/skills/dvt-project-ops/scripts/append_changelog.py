#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def find_repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError("Visual_transformer repository root was not found")


def append_entry(repo_root: Path, text: str, *, now: datetime | None = None) -> dict[str, Any]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("Changelog text must not be empty")

    timestamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    entry_lines = [f"### {timestamp}", *[f"- {line}" for line in lines]]
    entry_text = "\n".join(entry_lines) + "\n"
    changelog_path = repo_root / "AGENTS_CHANGELOGS.md"
    existing = changelog_path.read_text(encoding="utf-8") if changelog_path.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    if existing and not existing.endswith("\n\n"):
        existing += "\n"
    changelog_path.write_text(existing + entry_text, encoding="utf-8")
    return {
        "success": True,
        "timestamp": timestamp,
        "path": str(changelog_path),
        "entry": entry_lines,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Append a timestamped DVT agent changelog entry")
    parser.add_argument("--text", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        payload = append_entry(find_repo_root(), args.text)
    except Exception as exc:  # noqa: BLE001
        payload = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
