from pathlib import Path
import ssl
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from services.installation_manager.infrastructure.staging_downloads import ReleaseDownloader
from services.installation_manager.infrastructure.staging_commands import Deadline, RetryPolicy

PAYLOAD = b"x" * 65536

class Handler(BaseHTTPRequestHandler):
    terminated = False
    def do_GET(self):
        if not type(self).terminated:
            type(self).terminated = True
            self.connection.shutdown(socket.SHUT_RDWR)
            self.close_connection = True
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(PAYLOAD)))
        self.end_headers()
        self.wfile.write(PAYLOAD)

if sys.argv[1] == "server":
    server = ThreadingHTTPServer(("0.0.0.0", 9443), Handler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain("/tls/tls.crt", "/tls/tls.key")
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    server.serve_forever()
else:
    mtu = int(Path("/sys/class/net/eth0/mtu").read_text())
    assert mtu == 1280, mtu
    origin = "https://fixture-tls:9443"
    client = ReleaseDownloader(frozenset({origin}), Path("/public-ca.crt"))
    result = client.get(origin + "/asset", len(PAYLOAD), cwd=Path("/case"), deadline=Deadline(RetryPolicy(total_seconds=10, io_seconds=4, attempts=2, initial_delay=0.05)))
    assert result == PAYLOAD
    print(f"PASS: TLS asset {len(result)} bytes on bridge MTU {mtu}; first transfer reset, same URL retried")
