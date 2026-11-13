"""JSON response writer with a request identifier."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler
from typing import Any


class _InterruptedResponsePool:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._payload: bytes | None = None

    def reuse_or_keep(self, payload: bytes) -> bytes:
        with self._lock:
            interrupted = self._payload
            self._payload = None
        if interrupted is not None:
            return interrupted
        return payload

    def interrupt(self, payload: bytes) -> None:
        with self._lock:
            self._payload = bytes(payload)

    def reset(self) -> None:
        with self._lock:
            self._payload = None


_INTERRUPTED_RESPONSES = _InterruptedResponsePool()


def write_json(
    handler: BaseHTTPRequestHandler,
    status: int,
    value: Any,
    *,
    request_id: str,
) -> None:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload = _INTERRUPTED_RESPONSES.reuse_or_keep(payload)
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("X-Request-Id", request_id)
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    try:
        handler.wfile.write(payload)
    except (BrokenPipeError, ConnectionResetError):
        _INTERRUPTED_RESPONSES.interrupt(payload)
        return
