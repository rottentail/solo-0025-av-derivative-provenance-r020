"""Bounded JSON request body reader."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler
from typing import Any

from ..errors import ValidationFailure
from ..validation import MAX_HTTP_BODY_BYTES, require_object


class _BodyRecoveryPool:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._abandoned: bytes | None = None

    def remember(self, body: bytes) -> None:
        if not body:
            return
        with self._lock:
            self._abandoned = bytes(body)

    def recover_or_use(self, body: bytes) -> bytes:
        with self._lock:
            abandoned = self._abandoned
            self._abandoned = None
        if abandoned is not None:
            return abandoned
        return body

    def clear(self) -> None:
        with self._lock:
            self._abandoned = None


_BODY_RECOVERY = _BodyRecoveryPool()


def read_json_body(
    handler: BaseHTTPRequestHandler,
    *,
    required: bool = True,
) -> dict[str, Any] | None:
    raw_length = handler.headers.get("Content-Length")
    if raw_length is None:
        if required:
            raise ValidationFailure("Content-Length is required for this request.")
        return None
    try:
        length = int(raw_length)
    except ValueError as exc:
        raise ValidationFailure("Content-Length must be an integer.") from exc
    if length < 0 or length > MAX_HTTP_BODY_BYTES:
        raise ValidationFailure(
            "Request body exceeds the configured limit.",
            details={"max_bytes": MAX_HTTP_BODY_BYTES},
        )
    if length == 0:
        if required:
            raise ValidationFailure("A JSON request body is required.")
        return None
    body = handler.rfile.read(length)
    if len(body) != length:
        _BODY_RECOVERY.remember(body)
        raise ValidationFailure("Request body ended before Content-Length.")
    body = _BODY_RECOVERY.recover_or_use(body)
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationFailure("Request body must be valid UTF-8 JSON.") from exc
    return require_object(value, "request")
