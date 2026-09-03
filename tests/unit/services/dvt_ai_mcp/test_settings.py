from __future__ import annotations

import os

os.environ.setdefault("DVT_ENVIRONMENT", "dev")

from services.dvt_ai_mcp.settings import Settings


def test_transport_allowlists_are_exact() -> None:
    configured = Settings(
        gateway_url="http://gateway:8000",
        internal_secret="x" * 32,
        host="0.0.0.0",
        port=8000,
        public_urls=("https://dvt.example", "https://dvt.example:8443"),
    )

    assert configured.transport_allowlists() == (
        ["dvt.example", "dvt.example:8443"],
        ["https://dvt.example", "https://dvt.example:8443"],
    )
