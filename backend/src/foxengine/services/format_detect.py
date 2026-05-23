"""Heuristic text ingest format detection and CSV column → field confidence."""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from foxengine.dsl.fields import INGEST_CANONICAL_FIELDS

FormatName = Literal["jsonl", "csv", "combo", "txt"]

LINE_VALUE_HEADER = "$value"
_PREVIEW_OBJECT_LIMIT = 12

CANONICAL_FIELDS = INGEST_CANONICAL_FIELDS
CANONICAL = frozenset(CANONICAL_FIELDS)

_HEADER_ALIASES: dict[str, tuple[str, float]] = {
    "email": ("email", 1.0),
    "e-mail": ("email", 0.95),
    "mail": ("email", 0.7),
    "email_address": ("email", 0.95),
    "user_email": ("email", 0.9),
    "phone": ("phone", 1.0),
    "telephone": ("phone", 0.9),
    "mobile": ("phone", 0.85),
    "msisdn": ("phone", 0.9),
    "tel": ("phone", 0.75),
    "phone_number": ("phone", 0.95),
    "username": ("username", 1.0),
    "user": ("username", 0.8),
    "login": ("username", 0.75),
    "nick": ("username", 0.65),
    "id_card": ("id_card", 1.0),
    "id": ("id_card", 0.55),
    "national_id": ("id_card", 0.85),
    "full_name": ("full_name", 1.0),
    "name": ("full_name", 0.7),
    "firstname": ("first_name", 0.9),
    "first_name": ("first_name", 1.0),
    "lastname": ("last_name", 0.9),
    "last_name": ("last_name", 1.0),
    "dob": ("dob", 1.0),
    "birthdate": ("dob", 0.85),
    "gender": ("gender", 1.0),
    "address": ("address", 1.0),
    "city": ("city", 1.0),
    "country": ("country", 1.0),
    "zip": ("zip", 1.0),
    "postal": ("zip", 0.85),
    "ip": ("ip", 1.0),
    "ip_address": ("ip", 0.95),
    "user_agent": ("user_agent", 1.0),
    "ua": ("user_agent", 0.75),
    "isp": ("isp", 1.0),
    "phone_carrier": ("phone_carrier", 1.0),
    "carrier": ("phone_carrier", 0.8),
    "password": ("password", 1.0),
    "pass": ("password", 0.75),
    "passwd": ("password", 0.85),
    "password_hash": ("password_hash", 1.0),
    "hash": ("password_hash", 0.65),
    "last_seen": ("last_seen", 1.0),
}

_HEADER_PATTERNS: dict[str, tuple[tuple[str, float], ...]] = {
    "email": (
        (r"\be\s?mail\b", 0.92),
        (r"\bmail\b", 0.7),
    ),
    "phone": (
        (r"\bphone\b", 0.9),
        (r"\btelephone\b", 0.9),
        (r"\bmobile\b", 0.86),
        (r"\bcell(?:ular)?\b", 0.78),
        (r"\btelefono\b", 0.86),
        (r"\bcellulare\b", 0.86),
        (r"\bmsisdn\b", 0.9),
        (r"\btel\b", 0.76),
    ),
    "username": (
        (r"\buser\s?name\b", 0.95),
        (r"\blogin\b", 0.76),
        (r"\bnick(?:name)?\b", 0.68),
        (r"\bhandle\b", 0.72),
    ),
    "id_card": (
        (r"\bnational\s?id\b", 0.86),
        (r"\bid\s?card\b", 0.92),
    ),
    "full_name": (
        (r"\bfull\s?name\b", 0.96),
        (r"^name$", 0.7),
        (r"\bdisplay\s?name\b", 0.82),
    ),
    "first_name": (
        (r"\bfirst\s?name\b", 0.96),
        (r"\bgiven\s?name\b", 0.9),
        (r"^nome$", 0.82),
        (r"^nombre$", 0.78),
        (r"\bforename\b", 0.82),
    ),
    "last_name": (
        (r"\blast\s?name\b", 0.96),
        (r"\bsur\s?name\b", 0.9),
        (r"\bfamily\s?name\b", 0.9),
        (r"\bcognome\b", 0.9),
        (r"\bapellido\b", 0.82),
    ),
    "dob": (
        (r"\bdate\s?of\s?birth\b", 0.95),
        (r"\bbirth\s?date\b", 0.88),
        (r"\bdob\b", 1.0),
    ),
    "address": (
        (r"\baddress\b", 0.92),
        (r"\bstreet\b", 0.76),
        (r"\bindirizzo\b", 0.88),
        (r"\bdireccion\b", 0.78),
        (r"\badresse\b", 0.78),
    ),
    "city": (
        (r"\bcity\b", 0.94),
        (r"\btown\b", 0.82),
        (r"\bcitt[àa]\b", 0.86),
        (r"\blocality\b", 0.78),
        (r"\bciudad\b", 0.82),
    ),
    "country": (
        (r"\bcountry\b", 0.94),
        (r"\bnation(?:ality)?\b", 0.82),
        (r"\bpaese\b", 0.78),
        (r"\bpais\b", 0.78),
    ),
    "zip": (
        (r"\bzip\b", 0.94),
        (r"\bpostal\s?code\b", 0.9),
        (r"\bpost\s?code\b", 0.86),
        (r"\bcap\b", 0.82),
    ),
    "ip": (
        (r"\bip\s?address\b", 0.96),
        (r"^ip$", 1.0),
    ),
    "user_agent": ((r"\buser\s?agent\b", 0.96),),
    "isp": ((r"\bisp\b", 1.0),),
    "phone_carrier": ((r"\bcarrier\b", 0.8),),
    "password": (
        (r"\bpassword\b", 1.0),
        (r"\bpasswd\b", 0.86),
        (r"^pass$", 0.76),
    ),
    "password_hash": (
        (r"\bpassword\s?hash\b", 1.0),
        (r"^hash$", 0.66),
    ),
    "last_seen": (
        (r"\blast\s?seen\b", 0.94),
        (r"\blast\s?login\b", 0.82),
    ),
}


def _norm_header(h: str) -> str:
    return re.sub(r"[\s-]+", "_", h.strip().lower())


def _norm_header_words(h: str) -> str:
    normalized = re.sub(r"[^a-z0-9à]", " ", h.strip().lower())
    return re.sub(r"\s+", " ", normalized).strip()


def score_header(header: str) -> list[tuple[str, float]]:
    """Return up to 5 (canonical_field, confidence) guesses for a CSV header."""
    nh = _norm_header(header)
    nw = _norm_header_words(header)
    out: list[tuple[str, float]] = []
    if nh in CANONICAL:
        out.append((nh, 1.0))
    if nh in _HEADER_ALIASES:
        field, conf = _HEADER_ALIASES[nh]
        out.append((field, conf))
    for alias, (field, conf) in _HEADER_ALIASES.items():
        if alias in nh and nh != alias:
            out.append((field, max(0.55, conf - 0.15)))
    if "email" in nh and nh not in _HEADER_ALIASES and nh != "email":
        out.append(("email", 0.72))
    if "phone" in nh and nh not in ("phone", "microphone"):
        out.append(("phone", 0.72))
    for field, patterns in _HEADER_PATTERNS.items():
        for pattern, conf in patterns:
            if re.search(pattern, nw, re.IGNORECASE):
                out.append((field, conf))
    best: dict[str, float] = {}
    for field, c in out:
        if c > best.get(field, 0.0):
            best[field] = c
    ranked = sorted(best.items(), key=lambda x: -x[1])
    return ranked[:5]


def _sample_lines(text: str, max_lines: int = 80) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        s = raw.strip()
        if s:
            lines.append(s)
        if len(lines) >= max_lines:
            break
    return lines


_COMBO_LINE = re.compile(r"^[^@\s]+@[^@\s]+\.[^:\s]+:.+$")


def _sniff_combo(lines: list[str]) -> tuple[bool, float]:
    if not lines:
        return False, 0.0
    ok = 0
    for line in lines[:60]:
        if _COMBO_LINE.match(line):
            ok += 1
    ratio = ok / min(len(lines), 60)
    return ratio >= 0.65, ratio


def _sniff_jsonl(lines: list[str]) -> tuple[bool, float]:
    if not lines:
        return False, 0.0
    ok = 0
    for line in lines[:60]:
        try:
            v = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(v, dict):
            ok += 1
    denom = min(len(lines), 60)
    ratio = ok / denom if denom else 0.0
    return ratio >= 0.72, ratio


_CSV_DELIMITER_CANDIDATES = ",;\t|"


def is_delimited_text_filename(inner_filename: str) -> bool:
    lower = inner_filename.lower()
    return lower.endswith((".csv", ".txt", ".tsv"))


def _score_csv_delimiter(text: str, delim: str) -> tuple[list[str] | None, float]:
    sample = text[:50_000]
    if not sample.strip():
        return None, 0.0
    reader = csv.reader(io.StringIO(sample), delimiter=delim)
    rows = list(reader)
    if not rows:
        return None, 0.0
    header = [h.strip() for h in rows[0]]
    if not any(header):
        return None, 0.3
    body_rows = rows[1:6]
    score = 0.55
    if len(header) >= 2:
        score = 0.75
    if all(len(r) == len(header) for r in body_rows if r):
        score = min(0.95, score + 0.15)
    return header, score


def _sniff_csv(text: str) -> tuple[str | None, list[str] | None, float]:
    sample = text[:50_000]
    if not sample.strip():
        return None, None, 0.0
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=_CSV_DELIMITER_CANDIDATES)
        delim = dialect.delimiter
        headers, score = _score_csv_delimiter(text, delim)
        return delim, headers, score
    except csv.Error:
        pass
    best_delim: str | None = None
    best_headers: list[str] | None = None
    best_score = 0.0
    for delim in _CSV_DELIMITER_CANDIDATES:
        headers, score = _score_csv_delimiter(text, delim)
        if score > best_score:
            best_delim, best_headers, best_score = delim, headers, score
    if best_score < 0.55:
        return None, None, 0.0
    return best_delim, best_headers, best_score


def _detect_result_for_csv(text: str, delim: str) -> DetectResult:
    headers, csv_c = _score_csv_delimiter(text, delim)
    if not headers:
        return DetectResult(
            format="csv",
            format_confidence=0.35,
            csv_delimiter=delim,
            headers=None,
            column_guesses={},
            recommended_column_map={},
            sample_rows=[],
        )
    col_guess: dict[str, list[dict[str, Any]]] = {}
    for h in headers:
        if not h:
            continue
        ranked = score_header(h)
        col_guess[h] = [{"field": f, "confidence": c} for f, c in ranked[:3]]
    rec = _build_recommended_map(headers)
    return DetectResult(
        format="csv",
        format_confidence=max(csv_c, 0.6),
        csv_delimiter=delim,
        headers=headers,
        column_guesses=col_guess,
        recommended_column_map=rec,
        sample_rows=_sample_csv_rows(text, delim, headers),
    )


@dataclass
class DetectResult:
    format: FormatName
    format_confidence: float
    csv_delimiter: str | None
    headers: list[str] | None
    column_guesses: dict[str, list[dict[str, Any]]]
    recommended_column_map: dict[str, str]
    sample_rows: list[dict[str, str]]


def _build_recommended_map(headers: list[str]) -> dict[str, str]:
    """Greedy one-to-one header -> field from best scores."""
    candidates: list[tuple[float, str, str]] = []
    for h in headers:
        if not h:
            continue
        for field, conf in score_header(h):
            candidates.append((conf, h, field))
    candidates.sort(key=lambda x: -x[0])
    used_fields: set[str] = set()
    used_headers: set[str] = set()
    out: dict[str, str] = {}
    for conf, h, field in candidates:
        if conf < 0.58:
            continue
        if h in used_headers or field in used_fields:
            continue
        out[h] = field
        used_headers.add(h)
        used_fields.add(field)
    return out


def _sample_csv_rows(
    text: str, delim: str, headers: list[str], n: int = 10
) -> list[dict[str, str]]:
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = list(reader)
    if len(rows) < 2:
        return []
    out: list[dict[str, str]] = []
    for cells in rows[1 : 1 + n]:
        row: dict[str, str] = {}
        for i, h in enumerate(headers):
            if not h:
                continue
            row[h] = cells[i] if i < len(cells) else ""
        out.append(row)
    return out


def _sample_jsonl_rows(lines: list[str], n: int = _PREVIEW_OBJECT_LIMIT) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for line in lines:
        if len(out) >= n:
            break
        try:
            v = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(v, dict):
            out.append({str(k): str(val) for k, val in v.items()})
    return out


def _headers_from_objects(objects: list[dict[str, Any]], limit: int = 40) -> list[str]:
    seen: set[str] = set()
    headers: list[str] = []
    for obj in objects:
        for key in obj:
            sk = str(key)
            if sk in seen:
                continue
            seen.add(sk)
            headers.append(sk)
            if len(headers) >= limit:
                return headers
    return headers


def _column_guesses_for_headers(headers: list[str]) -> dict[str, list[dict[str, Any]]]:
    col_guess: dict[str, list[dict[str, Any]]] = {}
    for h in headers:
        if not h:
            continue
        ranked = score_header(h)
        col_guess[h] = [{"field": f, "confidence": c} for f, c in ranked[:3]]
    return col_guess


def _detect_jsonl_result(
    lines: list[str],
    *,
    format_confidence: float,
    key_guess_mode: Literal["identity", "score"] = "score",
) -> DetectResult:
    guesses: dict[str, list[dict[str, Any]]] = {}
    headers: list[str] = []
    sample_rows = _sample_jsonl_rows(lines)
    if sample_rows:
        headers = list(sample_rows[0].keys())[:40]
        if key_guess_mode == "identity":
            for k in headers:
                guesses[k] = [{"field": k, "confidence": 1.0}]
        else:
            guesses = _column_guesses_for_headers(headers)
    recommended = _build_recommended_map(headers) if headers else {}
    return DetectResult(
        format="jsonl",
        format_confidence=format_confidence,
        csv_delimiter=None,
        headers=headers or None,
        column_guesses=guesses,
        recommended_column_map=recommended,
        sample_rows=sample_rows,
    )


def _detect_txt_result(lines: list[str], *, format_confidence: float) -> DetectResult:
    sample_rows = [{LINE_VALUE_HEADER: ln} for ln in lines[:_PREVIEW_OBJECT_LIMIT]]
    return DetectResult(
        format="txt",
        format_confidence=format_confidence,
        csv_delimiter=None,
        headers=[LINE_VALUE_HEADER],
        column_guesses={},
        recommended_column_map={},
        sample_rows=sample_rows,
    )


def _parse_json_document_objects(data: bytes) -> list[dict[str, Any]] | None:
    text = data.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):
        return [x for x in parsed if isinstance(x, dict)][: _PREVIEW_OBJECT_LIMIT * 4]
    return None


def _detect_json_document_result(data: bytes) -> DetectResult | None:
    objects = _parse_json_document_objects(data)
    if not objects:
        return None
    sample_objects = objects[:_PREVIEW_OBJECT_LIMIT]
    headers = _headers_from_objects(sample_objects)
    sample_rows = [
        {str(k): str(val) for k, val in obj.items()} for obj in sample_objects
    ]
    return DetectResult(
        format="jsonl",
        format_confidence=0.9,
        csv_delimiter=None,
        headers=headers or None,
        column_guesses=_column_guesses_for_headers(headers),
        recommended_column_map=_build_recommended_map(headers) if headers else {},
        sample_rows=sample_rows,
    )


def analyze_text_payload(
    inner_filename: str,
    data: bytes,
    *,
    csv_delimiter: str | None = None,
) -> DetectResult:
    text = data.decode("utf-8", errors="replace")
    lines = _sample_lines(text)
    lower = inner_filename.lower()

    if csv_delimiter is not None:
        delim = csv_delimiter if len(csv_delimiter) == 1 else ","
        if is_delimited_text_filename(inner_filename):
            return _detect_result_for_csv(text, delim)

    if lower.endswith(".json"):
        doc = _detect_json_document_result(data)
        if doc is not None:
            return doc
        j_ok, j_ratio = _sniff_jsonl(lines)
        return _detect_jsonl_result(
            lines,
            format_confidence=max(j_ratio, 0.5) if j_ok else 0.35,
            key_guess_mode="score",
        )

    if lower.endswith(".txt"):
        return _detect_txt_result(lines, format_confidence=0.85)

    if lower.endswith(".jsonl") or lower.endswith(".ndjson"):
        j_ok, j_ratio = _sniff_jsonl(lines)
        return _detect_jsonl_result(
            lines,
            format_confidence=max(j_ratio, 0.85),
            key_guess_mode="identity",
        )

    is_combo, combo_ratio = _sniff_combo(lines)
    if is_combo:
        return DetectResult(
            format="combo",
            format_confidence=combo_ratio,
            csv_delimiter=":",
            headers=["email", "password"],
            column_guesses={
                "col0": [{"field": "email", "confidence": combo_ratio}],
                "col1": [{"field": "password", "confidence": combo_ratio}],
            },
            recommended_column_map={},
            sample_rows=[
                {"email": ln.split(":", 1)[0], "password": ln.split(":", 1)[1]}
                for ln in lines[:_PREVIEW_OBJECT_LIMIT]
                if ":" in ln
            ],
        )

    j_ok, j_ratio = _sniff_jsonl(lines)
    delim, headers, csv_c = _sniff_csv(text)

    if j_ok and j_ratio >= (csv_c or 0) and j_ratio >= 0.72:
        return _detect_jsonl_result(lines, format_confidence=j_ratio)

    if delim and headers:
        return _detect_result_for_csv(text, delim)

    if j_ok:
        return _detect_jsonl_result(lines, format_confidence=j_ratio)

    if lines:
        return _detect_txt_result(lines, format_confidence=0.55)

    return DetectResult(
        format="csv",
        format_confidence=0.35,
        csv_delimiter=",",
        headers=None,
        column_guesses={},
        recommended_column_map={},
        sample_rows=[],
    )


def detect_for_ingest(
    inner_filename: str,
    data: bytes,
    format_hint: str,
) -> tuple[str, dict[str, Any]]:
    """Return (format, checkpoint_extras) for job checkpoint.

    ``format_hint`` is ``auto``, ``jsonl``, ``csv``, or ``combo``.
    """
    hint = format_hint.strip().lower()
    d = analyze_text_payload(inner_filename, data)

    if hint == "auto":
        extras: dict[str, Any] = {
            "detect_confidence": d.format_confidence,
            "csv_delimiter": d.csv_delimiter or ",",
        }
        if d.format in ("csv", "jsonl"):
            extras["column_map"] = dict(d.recommended_column_map)
        else:
            extras["column_map"] = {}
        return d.format, extras

    extras: dict[str, Any] = {"detect_confidence": d.format_confidence}
    if hint == "csv":
        extras["csv_delimiter"] = d.csv_delimiter if d.format == "csv" else ","
        extras["column_map"] = dict(d.recommended_column_map) if d.format == "csv" else {}
        return "csv", extras
    if hint == "jsonl":
        extras["csv_delimiter"] = ","
        extras["column_map"] = (
            dict(d.recommended_column_map) if d.format == "jsonl" else {}
        )
        return "jsonl", extras
    if hint == "combo":
        extras["csv_delimiter"] = ":"
        extras["column_map"] = {}
        return "combo", extras

    raise ValueError(f"unknown format hint: {hint!r}")
