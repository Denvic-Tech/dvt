from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, NamedTuple
from urllib import error, request


DEFAULT_TIMEOUT_SEC = 30


class OpenAPISnapshot(NamedTuple):
    source_url: str
    document: dict[str, Any]
    canonical_json: str
    pretty_json: str
    sha256: str


def split_url_entries(raw_value: str) -> list[str]:
    return [entry.strip() for entry in raw_value.split(";") if entry.strip()]


def build_default_openapi_url(public_url: str) -> str:
    normalized = public_url.strip().rstrip("/")
    if not normalized:
        raise RuntimeError("Public Gateway URL is empty.")
    if normalized.endswith("/api"):
        return f"{normalized}/openapi.json"
    return f"{normalized}/api/openapi.json"


def build_default_openapi_urls(public_url: str) -> list[str]:
    candidates = split_url_entries(public_url)
    if not candidates:
        raise RuntimeError("Public Gateway URL is empty.")
    return [build_default_openapi_url(candidate) for candidate in candidates]


def load_openapi_document(url: str, timeout_sec: int = DEFAULT_TIMEOUT_SEC) -> dict[str, Any]:
    request_headers = {
        "Accept": "application/json",
        "User-Agent": "dvt-gateway-sdk-openapi-hash",
    }
    api_request = request.Request(url, headers=request_headers)
    try:
        with request.urlopen(api_request, timeout=timeout_sec) as response:
            payload = response.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Failed to fetch OpenAPI from {url}: HTTP {exc.code}\n{body}"
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(f"Failed to fetch OpenAPI from {url}: {exc.reason}") from exc

    try:
        document = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Gateway OpenAPI is not valid JSON: {url}") from exc

    if not isinstance(document, dict):
        raise RuntimeError(f"Gateway OpenAPI root must be an object: {url}")
    return document


def canonicalize_openapi_document(document: dict[str, Any]) -> tuple[str, str]:
    canonical_json = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    pretty_json = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"
    return canonical_json, pretty_json


def calculate_openapi_sha256(canonical_json: str) -> str:
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def generate_snapshot(url: str, timeout_sec: int = DEFAULT_TIMEOUT_SEC) -> OpenAPISnapshot:
    document = load_openapi_document(url, timeout_sec=timeout_sec)
    canonical_json, pretty_json = canonicalize_openapi_document(document)
    return OpenAPISnapshot(
        source_url=url,
        document=document,
        canonical_json=canonical_json,
        pretty_json=pretty_json,
        sha256=calculate_openapi_sha256(canonical_json),
    )


def generate_snapshot_from_candidates(
    url_candidates: list[str],
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
) -> OpenAPISnapshot:
    normalized_candidates = list(
        dict.fromkeys(candidate.strip() for candidate in url_candidates if candidate.strip())
    )
    if not normalized_candidates:
        raise RuntimeError("No OpenAPI URLs provided.")

    failures: list[str] = []
    last_error: Exception | None = None
    for url in normalized_candidates:
        try:
            return generate_snapshot(url, timeout_sec=timeout_sec)
        except Exception as exc:
            last_error = exc
            failures.append(str(exc))

    if len(normalized_candidates) == 1 and last_error is not None:
        raise last_error

    failure_details = "\n".join(f"- {failure}" for failure in failures)
    raise RuntimeError(
        "Failed to fetch OpenAPI from any configured URL:\n"
        f"{failure_details}"
    )


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def resolve_openapi_url_candidates_from_env() -> list[str]:
    explicit_url = (os.environ.get("GATEWAY_SDK_OPENAPI_URL") or "").strip()
    if explicit_url:
        candidates = split_url_entries(explicit_url)
        if not candidates:
            raise RuntimeError("GATEWAY_SDK_OPENAPI_URL is empty.")
        return candidates

    public_url = (os.environ.get("DVT_DEV_PUBLIC_URL") or "").strip()
    if not public_url:
        raise RuntimeError("GATEWAY_SDK_OPENAPI_URL or DVT_DEV_PUBLIC_URL must be set.")
    return build_default_openapi_urls(public_url)


def resolve_default_url_from_env() -> str:
    return resolve_openapi_url_candidates_from_env()[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate canonical Gateway OpenAPI hash.")
    parser.add_argument("--url")
    parser.add_argument("--timeout-sec", type=int, default=DEFAULT_TIMEOUT_SEC)
    parser.add_argument("--hash-output")
    parser.add_argument("--snapshot-output")
    parser.add_argument(
        "--print-json",
        choices=["hash", "snapshot", "metadata"],
        default="metadata",
    )
    args = parser.parse_args()

    try:
        raw_url = (args.url or "").strip()
        url_candidates = split_url_entries(raw_url) if raw_url else resolve_openapi_url_candidates_from_env()
        snapshot = generate_snapshot_from_candidates(
            url_candidates,
            timeout_sec=max(args.timeout_sec, 1),
        )

        if args.hash_output:
            write_text(Path(args.hash_output).expanduser().resolve(), snapshot.sha256 + "\n")
        if args.snapshot_output:
            write_text(Path(args.snapshot_output).expanduser().resolve(), snapshot.pretty_json)

        if args.print_json == "hash":
            print(snapshot.sha256)
        elif args.print_json == "snapshot":
            print(snapshot.pretty_json, end="")
        else:
            print(
                json.dumps(
                    {
                        "source_url": snapshot.source_url,
                        "sha256": snapshot.sha256,
                    },
                    ensure_ascii=False,
                )
            )
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
