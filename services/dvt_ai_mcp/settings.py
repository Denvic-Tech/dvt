from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


def _public_urls() -> tuple[str, ...]:
    raw = os.getenv("DVT_PUBLIC_URL", "http://localhost")
    urls = tuple(item.strip().rstrip("/") for item in raw.split(";") if item.strip())
    if not urls:
        raise RuntimeError("DVT_PUBLIC_URL must contain at least one URL.")
    for url in urls:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise RuntimeError(f"Invalid DVT_PUBLIC_URL entry: {url!r}")
    return urls


@dataclass(frozen=True, slots=True)
class Settings:
    gateway_url: str
    internal_secret: str
    host: str
    port: int
    public_urls: tuple[str, ...]

    @classmethod
    def from_env(cls) -> Settings:
        secret = os.getenv("DVT_AI_MCP_INTERNAL_SECRET", "")
        environment = os.getenv("ENVIRONMENT", os.getenv("DVT_ENVIRONMENT", "prod")).lower()
        if environment not in {"dev", "development", "test"} and len(secret) < 32:
            raise RuntimeError(
                "DVT_AI_MCP_INTERNAL_SECRET must contain at least 32 characters in production."
            )
        if not secret:
            secret = "dev-ai-mcp-internal-secret-change-me"
        return cls(
            gateway_url=os.getenv("DVT_AI_MCP_GATEWAY_URL", "http://gateway:8000").rstrip("/"),
            internal_secret=secret,
            host=os.getenv("DVT_AI_MCP_HOST", "0.0.0.0"),
            port=int(os.getenv("DVT_AI_MCP_PORT", "8000")),
            public_urls=_public_urls(),
        )

    def transport_allowlists(self) -> tuple[list[str], list[str]]:
        hosts: set[str] = set()
        origins: set[str] = set()
        for url in self.public_urls:
            parsed = urlparse(url)
            origins.add(f"{parsed.scheme}://{parsed.netloc}")
            hosts.add(parsed.netloc)
        return sorted(hosts), sorted(origins)


settings = Settings.from_env()
