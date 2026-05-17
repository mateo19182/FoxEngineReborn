"""HTTP client for OpenAI-compatible chat APIs (llama.cpp server, LM Studio, vLLM, etc.)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from foxengine.config import Settings, get_settings


class LlmUnavailableError(RuntimeError):
    pass


class LlmError(RuntimeError):
    pass


def _llm_headers(s: Settings) -> dict[str, str]:
    if s.llm_api_key and str(s.llm_api_key).strip():
        return {"Authorization": f"Bearer {str(s.llm_api_key).strip()}"}
    return {}


def _health_url(s: Settings) -> str | None:
    p = (s.llm_health_path or "").strip()
    if not p or p.lower() in ("off", "none", "skip"):
        return None
    return f"{s.llm_base_url.rstrip('/')}/{p.lstrip('/')}"


async def llm_health_status() -> str:
    s = get_settings()
    if not s.llm_enabled:
        return "disabled"
    url = _health_url(s)
    if url is None:
        return "skipped"
    try:
        async with httpx.AsyncClient(timeout=s.llm_health_timeout_s) as client:
            r = await client.get(url, headers=_llm_headers(s))
            if r.status_code == 200:
                return "ok"
            return f"error: HTTP {r.status_code}"
    except Exception as e:
        return f"error: {e!s}"


async def chat_completion_messages(
    *,
    messages: list[dict[str, Any]],
    temperature: float = 0,
    max_tokens: int = 8000,
) -> str:
    s = get_settings()
    if not s.llm_enabled:
        raise LlmUnavailableError("LLM is disabled (FOX_LLM_ENABLED=false)")

    url = f"{s.llm_base_url.rstrip('/')}/v1/chat/completions"
    payload: dict[str, Any] = {
        "model": s.llm_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=s.llm_timeout_s) as client:
            r = await client.post(url, json=payload, headers=_llm_headers(s))
    except httpx.TimeoutException as e:
        raise LlmError("LLM request timed out") from e
    except httpx.RequestError as e:
        raise LlmUnavailableError(f"LLM unreachable: {e}") from e

    if r.status_code >= 500:
        raise LlmUnavailableError(f"LLM server error: HTTP {r.status_code}")
    if r.status_code != 200:
        raise LlmError(f"LLM rejected request: HTTP {r.status_code}: {r.text[:500]}")

    data = r.json()
    print(f"[LLM_CLIENT] Response status: {r.status_code}", flush=True)
    print(f"[LLM_CLIENT] Response data: {data}", flush=True)
    try:
        content = str(data["choices"][0]["message"]["content"]).strip()
        print(f"[LLM_CLIENT] Extracted content: {content!r}", flush=True)
        return content
    except (KeyError, IndexError, TypeError) as e:
        raise LlmError("unexpected LLM response shape") from e


async def chat_completion_messages_stream(
    *,
    messages: list[dict[str, Any]],
    temperature: float = 0,
    max_tokens: int = 8000,
) -> AsyncIterator[str]:
    """Yield text fragments from an OpenAI-compatible ``stream: true`` response."""
    s = get_settings()
    if not s.llm_enabled:
        raise LlmUnavailableError("LLM is disabled (FOX_LLM_ENABLED=false)")

    url = f"{s.llm_base_url.rstrip('/')}/v1/chat/completions"
    payload: dict[str, Any] = {
        "model": s.llm_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    try:
        async with httpx.AsyncClient(timeout=s.llm_timeout_s) as client:
            async with client.stream("POST", url, json=payload, headers=_llm_headers(s)) as r:
                if r.status_code >= 500:
                    raise LlmUnavailableError(f"LLM server error: HTTP {r.status_code}")
                if r.status_code != 200:
                    body = (await r.aread()).decode("utf-8", errors="replace")[:800]
                    raise LlmError(f"LLM rejected request: HTTP {r.status_code}: {body}")

                async for line in r.aiter_lines():
                    raw = line.strip()
                    if not raw or raw.startswith(":"):
                        continue
                    if not raw.startswith("data:"):
                        continue
                    data = raw.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj: dict[str, Any] = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = obj.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    choice0 = choices[0]
                    if not isinstance(choice0, dict):
                        continue
                    delta = choice0.get("delta")
                    if not isinstance(delta, dict):
                        continue
                    piece = delta.get("content")
                    if piece is None:
                        continue
                    text = str(piece)
                    if text:
                        yield text
    except httpx.TimeoutException as e:
        raise LlmError("LLM request timed out") from e
    except httpx.RequestError as e:
        raise LlmUnavailableError(f"LLM unreachable: {e}") from e


async def chat_completion(
    *,
    system: str,
    user: str,
    max_tokens: int = 8000,
) -> str:
    return await chat_completion_messages(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0,
        max_tokens=max_tokens,
    )
