"""Bounded JSON request body reader.

Every request owns its own body bytes.  A body is read exactly once, used by
the request that supplied it, and released together with the request.  When a
body cannot be framed completely (a shortened ``Content-Length`` stream, an
oversized length, or an unsupported transfer encoding) the connection is
retired instead of being reused: the unread remainder must never be parsed as
the beginning of a later request.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from typing import Any

from ..errors import ValidationFailure
from ..validation import MAX_HTTP_BODY_BYTES, require_object


def _retire_connection(handler: BaseHTTPRequestHandler) -> None:
    """Stop the server from reading another request from this connection."""

    handler.close_connection = True


def _declares_unread_body(handler: BaseHTTPRequestHandler) -> bool:
    encoding = (handler.headers.get("Transfer-Encoding") or "").strip()
    return bool(encoding)


def read_json_body(
    handler: BaseHTTPRequestHandler,
    *,
    required: bool = True,
) -> dict[str, Any] | None:
    raw_length = handler.headers.get("Content-Length")
    if raw_length is None:
        if _declares_unread_body(handler):
            _retire_connection(handler)
        if required:
            raise ValidationFailure("Content-Length is required for this request.")
        return None
    try:
        length = int(raw_length)
    except ValueError as exc:
        _retire_connection(handler)
        raise ValidationFailure("Content-Length must be an integer.") from exc
    if length < 0 or length > MAX_HTTP_BODY_BYTES:
        _retire_connection(handler)
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
        # The connection ended inside the declared body.  Any trailing bytes
        # belong to this request, not to a following one, so the connection
        # cannot safely carry another request.
        _retire_connection(handler)
        raise ValidationFailure("Request body ended before Content-Length.")

    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationFailure("Request body must be valid UTF-8 JSON.") from exc
    return require_object(value, "request")
