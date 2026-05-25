"""Tests for S3 streaming line reader."""

from __future__ import annotations

import pytest

from foxengine.services.ingest_s3_stream import iter_utf8_lines, read_body_bytes


class _ChunkBody:
    def __init__(self, data: bytes, *, chunk_size: int = 5) -> None:
        self._data = data
        self._chunk_size = chunk_size
        self._pos = 0

    async def read(self, n: int) -> bytes:
        if self._pos >= len(self._data):
            return b""
        chunk = self._data[self._pos : self._pos + n]
        self._pos += len(chunk)
        return chunk


@pytest.mark.asyncio
async def test_iter_utf8_lines_splits_on_newline() -> None:
    body = _ChunkBody(b"one\ntwo\nthree")
    lines = [line async for line in iter_utf8_lines(body, chunk_size=4)]
    assert lines == ["one", "two", "three"]


@pytest.mark.asyncio
async def test_iter_utf8_lines_handles_initial_prefix() -> None:
    body = _ChunkBody(b"rest", chunk_size=4)
    lines = [line async for line in iter_utf8_lines(body, chunk_size=4, initial=b"first\n")]
    assert lines == ["first", "rest"]


@pytest.mark.asyncio
async def test_read_body_bytes_with_initial() -> None:
    body = _ChunkBody(b"world", chunk_size=3)
    blob = await read_body_bytes(body, chunk_size=3, initial=b"hello ")
    assert blob == b"hello world"
