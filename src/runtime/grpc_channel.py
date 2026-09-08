import json
import asyncio

import grpc

import config


def _default_service_config(
        service: str,
        *services: str,
        timeout_seconds: float = 60.0
) -> str:
    """
    gRPC Service Config: базовый таймаут + ретраи на UNAVAILABLE.
    """
    services = [service, *services]
    cfg = {
        "methodConfig": [{
            "name": [
                {"service": service}
                for service in services
            ],
            "timeout": f"{timeout_seconds}s",
            "retryPolicy": {
                "maxAttempts": 3,
                "initialBackoff": "0.1s",
                "maxBackoff": "0.6s",
                "backoffMultiplier": 2.0,
                "retryableStatusCodes": ["UNAVAILABLE"]
            }
        }]
    }
    return json.dumps(cfg)


def default_channel_options(
        service: str,
        *services: str,
        max_send_message_length: float = 10 * 1024 * 1024,
        max_receive_message_length: float = 10 * 1024 * 1024,
        timeout_seconds: float = 60.0
):
    return (
        ("grpc.service_config", _default_service_config(
            service,
            *services,
            timeout_seconds=timeout_seconds
        )),
        ("grpc.enable_http_proxy", 0),
        ("grpc.max_send_message_length", max_send_message_length),
        ("grpc.max_receive_message_length", max_receive_message_length),

        # Keepalive settings - reduced from 10 hours to 5 minutes for faster connection recovery
        ("grpc.keepalive_time_ms", 5 * 60 * 1000),  # 5 minutes
        ("grpc.keepalive_timeout_ms", 20 * 1000),   # 20 seconds

        ("grpc.http2.max_pings_without_data", 0),
        ("grpc.http2.min_time_between_pings_ms", 60 * 1000),
        ("grpc.http2.min_ping_interval_without_data_ms", 5 * 60 * 1000),  # 5 minutes

        # Windows-specific socket buffer settings to prevent WinError 10035 (WSAEWOULDBLOCK)
        ("grpc.so_reuseaddr", 1),
        ("grpc.tcp_user_timeout", 20000),  # 20 seconds in milliseconds

        # TCP socket buffer sizes (helps with large message batching on Windows)
        ("grpc.http2.write_buffer_size", 1024 * 1024),  # 1MB write buffer
        ("grpc.http2.max_frame_size", 16384),  # 16KB max frame size (default)

        # Flow control window sizes to prevent buffer overflow
        ("grpc.http2.initial_sequence_number", 0),
        ("grpc.http2.stream_lookahead_bytes", 65536),  # 64KB lookahead
    )


class GRPCChannelManager:
    def __init__(
            self,
            target: str,
            service: str,
            *services: str,
            max_send_message_length: float = 10 * 1024 * 1024,
            max_receive_message_length: float = 10 * 1024 * 1024,
            timeout_seconds: float = 60.0
    ):
        self.target = target
        self.service = service
        self.services = services

        self.max_send_message_length = max_send_message_length
        self.max_receive_message_length = max_receive_message_length
        self.timeout_seconds = timeout_seconds

        self.lock = asyncio.Lock()
        self.channel: grpc.aio.Channel | None = None

    async def get_channel(self):
        async with self.lock:
            if self.channel is None:
                self.channel = grpc.aio.insecure_channel(
                    self.target,
                    options=default_channel_options(
                        self.service,
                        *self.services,
                        max_send_message_length=self.max_send_message_length,
                        max_receive_message_length=self.max_receive_message_length,
                        timeout_seconds=self.timeout_seconds,
                    ),
                )
            return self.channel

    async def close_channel(self):
        async with self.lock:
            if self.channel is not None:
                await self.channel.close()
