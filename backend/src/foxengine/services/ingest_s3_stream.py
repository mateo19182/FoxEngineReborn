"""Stream UTF-8 text lines from an async S3 object body without a full local copy."""

from __future__ import annotations

import codecs
from collections.abc import AsyncIterator
from typing import Any


async def iter_utf8_lines(
    body: Any,
    *,
    chunk_size: int,
    initial: bytes = b"",
) -> AsyncIterator[str]:
    """Yield lines from a streaming body (no trailing newline)."""
    pending = initial
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    while True:
        chunk = await body.read(chunk_size)
        if chunk:
            pending += chunk
        while True:
            nl = pending.find(b"\n")
            if nl < 0:
                break
            line_b, pending = pending[:nl], pending[nl + 1 :]
            yield decoder.decode(line_b)
        if not chunk:
            if pending:
                yield decoder.decode(pending)
            break


async def read_body_bytes(
    body: Any,
    *,
    chunk_size: int,
    initial: bytes = b"",
) -> bytes:
    """Read the remainder of a streaming body into memory."""
    parts = [initial] if initial else []
    while True:
        chunk = await body.read(chunk_size)
        if not chunk:
            break
        parts.append(chunk)
    return b"".join(parts)
