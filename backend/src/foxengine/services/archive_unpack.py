"""Unpack .zip, .tar / .tar.gz / .tgz, single-member .gz, and .7z into (inner_name, bytes) pairs."""

from __future__ import annotations

import gzip
import io
import logging
import tarfile
import zipfile
from pathlib import PurePosixPath

import py7zr

log = logging.getLogger(__name__)

_TEXT_SUFFIXES = frozenset(
    {
        ".csv",
        ".tsv",
        ".txt",
        ".json",
        ".jsonl",
        ".ndjson",
        ".log",
        ".sql",
    }
)
_SKIP_SUFFIXES = frozenset({".ds_store"})
_SKIP_PREFIXES = ("__macosx/",)


def _is_probably_text_member(name: str, data: bytes) -> bool:
    suf = PurePosixPath(name).suffix.lower()
    if suf in _SKIP_SUFFIXES:
        return False
    if suf and suf not in _TEXT_SUFFIXES and suf not in {".gz", ".zip", ".7z", ".tar"}:
        return False
    if len(data) == 0:
        return False
    sample = data[: min(len(data), 256_000)]
    if b"\x00" in sample[:8000]:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _zip_members(data: bytes) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            nl = name.lower()
            if any(nl.startswith(p) for p in _SKIP_PREFIXES):
                continue
            raw = zf.read(info)
            if _is_probably_text_member(name, raw):
                out.append((name, raw))
    return out


def _tar_members(data: bytes) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
        for m in tf.getmembers():
            if not m.isfile():
                continue
            name = m.name.replace("\\", "/")
            nl = name.lower()
            if any(nl.startswith(p) for p in _SKIP_PREFIXES):
                continue
            f = tf.extractfile(m)
            if f is None:
                continue
            raw = f.read()
            if _is_probably_text_member(name, raw):
                out.append((name, raw))
    return out


def _seven_zip_members(data: bytes) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    with py7zr.SevenZipFile(io.BytesIO(data), mode="r") as zf:
        for name, bio in zf.readall().items():
            if name.endswith("/"):
                continue
            name = name.replace("\\", "/")
            nl = name.lower()
            if any(nl.startswith(p) for p in _SKIP_PREFIXES):
                continue
            raw = bio.read()
            if _is_probably_text_member(name, raw):
                out.append((name, raw))
    return out


def _is_zip_magic(data: bytes) -> bool:
    return len(data) >= 4 and data[:4] == b"PK\x03\x04"


def _is_gzip_magic(data: bytes) -> bool:
    return len(data) >= 2 and data[0] == 0x1F and data[1] == 0x8B


def _is_tar_magic(data: bytes) -> bool:
    if len(data) < 264:
        return False
    return data[257:262] in (b"ustar", b"ustar\x00")


def unpack_archive(outer_filename: str, data: bytes) -> list[tuple[str, bytes]]:
    """Return [(inner_name, payload), ...]. If not an archive, [(outer_filename, data)]."""
    fn = (outer_filename or "upload.bin").replace("\\", "/")
    lower = fn.lower()

    if lower.endswith(".tar.gz") or lower.endswith(".tgz"):
        try:
            raw = gzip.decompress(data)
        except OSError:
            log.warning("gzip decompress failed for %s", fn)
            return [(fn, data)]
        members = _tar_members(raw)
        return members if members else [(fn, data)]

    if lower.endswith(".tar") or _is_tar_magic(data):
        members = _tar_members(data)
        return members if members else [(fn, data)]

    if lower.endswith(".zip") or _is_zip_magic(data):
        try:
            members = _zip_members(data)
        except zipfile.BadZipFile:
            return [(fn, data)]
        return members if members else [(fn, data)]

    if lower.endswith(".7z"):
        try:
            members = _seven_zip_members(data)
        except Exception as e:
            log.warning("7z unpack failed: %s", e)
            return [(fn, data)]
        return members if members else [(fn, data)]

    if lower.endswith(".gz"):
        try:
            inner = gzip.decompress(data)
        except OSError:
            return [(fn, data)]
        stem = PurePosixPath(fn).stem
        return [(stem, inner)]

    return [(fn, data)]


def merge_text_parts(parts: list[tuple[str, bytes]]) -> tuple[str, bytes]:
    """Concatenate UTF-8 text parts with a header comment per part."""
    chunks: list[str] = []
    for name, raw in parts:
        text = raw.decode("utf-8", errors="replace")
        chunks.append(f"# --- {name} ---\n{text}")
    joined = "\n\n".join(chunks).encode("utf-8")
    return ("merged.txt", joined)
