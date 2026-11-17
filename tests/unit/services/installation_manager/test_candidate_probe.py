from __future__ import annotations

import contextlib
import json
import socket
import ssl
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from services.installation_manager import candidate_executor
from services.installation_manager.infrastructure.operation_store import FORMAT_VERSION


def _server_tls(tmp_path, certificate_name):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, certificate_name)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=10))
        .not_valid_after(now + timedelta(minutes=10))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(certificate_name)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    certificate, private_key = tmp_path / "certificate.pem", tmp_path / "private.pem"
    certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    private_key.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(certificate, private_key)
    return server_context, ssl.create_default_context(cafile=certificate)


@pytest.mark.parametrize("certificate_name", ["localhost", "wrong-name.invalid"])
def test_manager_probe_uses_numeric_tcp_with_verified_localhost_and_bearer(
    tmp_path, monkeypatch, certificate_name,
) -> None:
    operation, instance, claim = uuid4(), uuid4(), uuid4()
    headers = []
    names = []
    body = json.dumps({
        "journal_format": FORMAT_VERSION,
        "operation": {
            "id": str(operation), "instance_id": str(instance),
            "last_owner": {"claim_id": str(claim)},
        },
    }).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            headers.append((self.path, self.headers["Host"], self.headers["Authorization"]))
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        tls, client = _server_tls(tmp_path, certificate_name)
        tls.set_servername_callback(lambda _sock, name, _ctx: names.append(name))
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        serve = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
        serve.start()
        try:
            def unavailable(*_args, **_kwargs):
                raise socket.gaierror("DNS is unavailable")

            monkeypatch.setattr(socket, "getaddrinfo", unavailable)
            if certificate_name == "localhost":
                monkeypatch.setattr(candidate_executor, "CandidateAuth", lambda _: SimpleNamespace(
                    host=f"localhost:{server.server_port}", machine="test-token",
                    probe_tls=lambda: client,
                ))
                store = SimpleNamespace(identity=lambda: SimpleNamespace(instance_id=instance))
                candidate_executor._probe(
                    {"address": "127.0.0.1", "port": server.server_port}, store, operation, claim,
                )
                assert headers == [
                    (f"/api/operations/{operation}", f"localhost:{server.server_port}",
                     "Bearer test-token"),
                ]
            else:
                connection = candidate_executor._ManagerConnection(
                    "127.0.0.1", server.server_port, client,
                )
                with contextlib.closing(connection), pytest.raises(ssl.SSLCertVerificationError):
                    connection.connect()
                assert headers == []
            assert names == ["localhost"]
        finally:
            server.shutdown()
            serve.join(timeout=2)
