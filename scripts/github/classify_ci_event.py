from __future__ import annotations

import argparse
import re
from dataclasses import dataclass


RC_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+-rc[0-9]+$")
STABLE_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


@dataclass(frozen=True)
class Classification:
    event_kind: str = ""
    release_tag: str = ""
    should_trigger: bool = False


def classify(event_name: str, ref: str) -> Classification:
    if event_name != "push":
        return Classification()
    if ref == "refs/heads/dev":
        return Classification(event_kind="dev", should_trigger=True)
    if not ref.startswith("refs/tags/"):
        return Classification()
    tag = ref.removeprefix("refs/tags/")
    if RC_RE.fullmatch(tag):
        return Classification(event_kind="rc", release_tag=tag, should_trigger=True)
    if STABLE_RE.fullmatch(tag):
        return Classification(event_kind="release", release_tag=tag, should_trigger=True)
    return Classification()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--github-output", required=True)
    args = parser.parse_args()

    result = classify(args.event_name, args.ref)
    with open(args.github_output, "a", encoding="utf-8") as output:
        output.write(f"should_trigger={'true' if result.should_trigger else 'false'}\n")
        output.write(f"event_kind={result.event_kind}\n")
        output.write(f"release_tag={result.release_tag}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
