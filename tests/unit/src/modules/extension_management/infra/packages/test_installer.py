import hashlib

import httpx
import pytest

from src.modules.extension_management.infra.packages import installer


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("size", "sha256", "error"),
    [
        (3, hashlib.sha256(b"abc").hexdigest(), None),
        (4, hashlib.sha256(b"abc").hexdigest(), "size"),
        (3, "0" * 64, "SHA-256"),
    ],
)
async def test_stage_remote_package_checks_bytes_before_extraction(
    monkeypatch, tmp_path, size, sha256, error
):
    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"a"
            yield b"bc"

    def respond(request):
        return httpx.Response(200, stream=Body())

    client = httpx.AsyncClient
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(installer.httpx, "AsyncClient", lambda **kwargs: client(transport=transport))
    monkeypatch.setattr(installer.tempfile, "tempdir", str(tmp_path))

    staged = []

    def capture(fileobj, filename):
        assert filename == "package.dvtx"
        result = fileobj.read()
        staged.append(result)
        return result

    monkeypatch.setattr(installer, "stage_extension_package", capture)

    manager = installer.ExtensionsInstallManager()
    url = "https://example.test/package.dvtx"
    if error:
        with pytest.raises(ValueError, match=error):
            await manager.stage_from_url(url, expected_size=size, expected_sha256=sha256)
        assert staged == []
    else:
        assert await manager.stage_from_url(url, expected_size=size, expected_sha256=sha256) == b"abc"
        assert staged == [b"abc"]
    assert not list(tmp_path.iterdir())
