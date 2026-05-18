"""Multi-turn assistant with read-only tools (jobs, batches, tags)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foxengine import schemas
from foxengine.db.models import Batch, Job, Tag, TagFamily
from foxengine.deps import Principal


def _strip_json_fence(raw: str) -> str:
    text = raw.strip()
    if not text.startswith("```"):
        return text
    parts = text.split("```")
    if len(parts) < 2:
        return text
    inner = parts[1]
    if inner.lstrip().lower().startswith("json"):
        inner = inner.lstrip()[4:].lstrip()
    return inner.strip()


def parse_fox_tools(content: str) -> list[dict[str, Any]] | None:
    raw = _strip_json_fence(content)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    tools = data.get("fox_tools")
    if not isinstance(tools, list) or not tools:
        return None
    out: list[dict[str, Any]] = []
    for t in tools[:6]:
        if not isinstance(t, dict):
            continue
        name = t.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        args = t.get("arguments")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            continue
        out.append({"name": name.strip(), "arguments": args})
    return out or None


def _can_view_job(principal: Principal, job: Job) -> bool:
    if "admin" in principal.roles:
        return True
    return job.owner_user_id is not None and job.owner_user_id == principal.user_id


def _job_out(row: Job, batch: Batch | None = None) -> schemas.JobOut:
    return schemas.JobOut(
        id=str(row.id),
        type=row.type,
        state=row.state,
        batch_id=str(row.batch_id) if row.batch_id else None,
        processed_rows=int(row.processed_rows),
        total_rows=int(row.total_rows) if row.total_rows is not None else None,
        result_uri=row.result_uri,
        error=row.error,
        started_at=row.started_at.isoformat() if row.started_at else None,
        finished_at=row.finished_at.isoformat() if row.finished_at else None,
        checkpoint=dict(row.checkpoint or {}),
        batch_name=batch.name if batch else None,
        source_filename=batch.source_filename if batch else None,
        accepted_rows=int(batch.accepted_rows) if batch else None,
        rejected_rows=int(batch.rejected_rows) if batch else None,
        duplicate_rows=int(batch.duplicate_rows) if batch else None,
        ingest_ts=batch.ingest_ts.isoformat() if batch else None,
    )


async def _tool_list_jobs(session: AsyncSession, principal: Principal) -> dict[str, Any]:
    q = select(Job).where(Job.type != "ingest_upload").order_by(Job.updated_at.desc()).limit(100)
    if "admin" not in principal.roles:
        q = q.where(Job.owner_user_id == principal.user_id)
    res = await session.execute(q)
    jobs = res.scalars().all()
    batch_ids = [j.batch_id for j in jobs if j.batch_id]
    batch_map: dict[UUID, Batch] = {}
    if batch_ids:
        batch_res = await session.execute(select(Batch).where(Batch.id.in_(batch_ids)))
        batch_map = {b.id: b for b in batch_res.scalars().all()}
    rows = [_job_out(j, batch_map[j.batch_id] if j.batch_id is not None else None) for j in jobs]
    return {"jobs": [r.model_dump(mode="json") for r in rows]}


async def _tool_get_job(
    session: AsyncSession, principal: Principal, arguments: dict[str, Any]
) -> dict[str, Any]:
    raw = arguments.get("job_id")
    if not isinstance(raw, str) or not raw.strip():
        return {"error": "missing job_id"}
    try:
        job_id = UUID(raw.strip())
    except ValueError:
        return {"error": "invalid job_id"}
    res = await session.execute(select(Job).where(Job.id == job_id))
    job = res.scalar_one_or_none()
    if job is None or not _can_view_job(principal, job):
        return {"error": "not found"}
    batch = None
    if job.batch_id:
        batch_res = await session.execute(select(Batch).where(Batch.id == job.batch_id))
        batch = batch_res.scalar_one_or_none()
    return {"job": _job_out(job, batch).model_dump(mode="json")}


async def _tool_list_batches(session: AsyncSession, arguments: dict[str, Any]) -> dict[str, Any]:
    lim = arguments.get("limit", 30)
    if not isinstance(lim, int) or isinstance(lim, bool):
        try:
            lim = int(lim)
        except (TypeError, ValueError):
            lim = 30
    lim = max(1, min(lim, 100))
    res = await session.execute(
        select(Batch).where(Batch.deleted_at.is_(None)).order_by(Batch.ingest_ts.desc()).limit(lim)
    )
    rows = res.scalars().all()
    out = [
        schemas.BatchOut(
            id=str(b.id),
            name=b.name,
            source_filename=b.source_filename,
            accepted_rows=int(b.accepted_rows),
            rejected_rows=int(b.rejected_rows),
            duplicate_rows=int(b.duplicate_rows),
            ingest_ts=b.ingest_ts.isoformat(),
        ).model_dump(mode="json")
        for b in rows
    ]
    return {"batches": out}


async def _tool_get_batch(session: AsyncSession, arguments: dict[str, Any]) -> dict[str, Any]:
    raw = arguments.get("batch_id")
    if not isinstance(raw, str) or not raw.strip():
        return {"error": "missing batch_id"}
    try:
        batch_id = UUID(raw.strip())
    except ValueError:
        return {"error": "invalid batch_id"}
    res = await session.execute(
        select(Batch).where(Batch.id == batch_id, Batch.deleted_at.is_(None))
    )
    b = res.scalar_one_or_none()
    if b is None:
        return {"error": "not found"}
    batch = schemas.BatchOut(
        id=str(b.id),
        name=b.name,
        source_filename=b.source_filename,
        accepted_rows=int(b.accepted_rows),
        rejected_rows=int(b.rejected_rows),
        duplicate_rows=int(b.duplicate_rows),
        ingest_ts=b.ingest_ts.isoformat(),
    )
    return {"batch": batch.model_dump(mode="json")}


async def _tool_list_tags(session: AsyncSession, arguments: dict[str, Any]) -> dict[str, Any]:
    lim = arguments.get("limit", 80)
    if not isinstance(lim, int) or isinstance(lim, bool):
        try:
            lim = int(lim)
        except (TypeError, ValueError):
            lim = 80
    lim = max(1, min(lim, 200))
    res = await session.execute(
        select(Tag, TagFamily.code)
        .select_from(Tag)
        .outerjoin(TagFamily, Tag.family_id == TagFamily.id)
        .where(Tag.deleted_at.is_(None))
        .order_by(Tag.name)
        .limit(lim)
    )
    rows = res.all()
    tags = [
        schemas.TagOut.from_tag(tag, family_code=family_code).model_dump(mode="json")
        for tag, family_code in rows
    ]
    return {"tags": tags, "truncated": len(tags) >= lim}


async def run_tool_calls(
    session: AsyncSession,
    principal: Principal,
    tool_calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for call in tool_calls:
        name = call["name"]
        args = call["arguments"]
        try:
            if name == "list_jobs":
                payload = await _tool_list_jobs(session, principal)
            elif name == "get_job":
                payload = await _tool_get_job(session, principal, args)
            elif name == "list_batches":
                payload = await _tool_list_batches(session, args)
            elif name == "get_batch":
                payload = await _tool_get_batch(session, args)
            elif name == "list_tags":
                payload = await _tool_list_tags(session, args)
            else:
                payload = {"error": f"unknown tool {name!r}"}
        except Exception as e:
            payload = {"error": str(e)}
        results.append({"tool": name, "result": payload})
    return results


_ASSISTANT_SYSTEM = (
    "You are FoxEngine's in-app assistant. FoxEngine stores leads; background work "
    "appears as Jobs (ingest, export, bulk_tag). Batches group ingest files. "
    "Tags label datasets.\n\n"
    "Speak naturally. Do not tell the user about fox_tools or raw JSON protocols.\n\n"
    "When you need live data from this server, respond with ONLY a single JSON object "
    "(no markdown fences, no other text):\n"
    '{"fox_tools":[{"name":"<name>","arguments":{}}]}\n\n'
    "Tools (read-only; job visibility follows the signed-in user):\n"
    "- list_jobs — arguments {}\n"
    '- get_job — arguments {"job_id":"<uuid>"}\n'
    '- list_batches — arguments {"limit":<optional int 1-100>}\n'
    '- get_batch — arguments {"batch_id":"<uuid>"}\n'
    '- list_tags — arguments {"limit":<optional int 1-200>}\n\n'
    "If you already have enough information, answer in plain language only (no JSON). "
    "Never invent job or batch ids."
)


def _history_to_messages(history: list[tuple[str, str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"role": "system", "content": _ASSISTANT_SYSTEM}]
    for role, content in history:
        if role not in ("user", "assistant"):
            continue
        text = content.strip()
        if not text:
            continue
        out.append({"role": role, "content": text})
    return out


async def run_assistant_turn(
    session: AsyncSession,
    principal: Principal,
    *,
    history: list[tuple[str, str]],
    max_llm_rounds: int = 8,
) -> str:
    from foxengine.services.llm_client import chat_completion_messages

    messages = _history_to_messages(history)
    if len(messages) <= 1:
        return "Send a message first."

    last = ""
    for _ in range(max_llm_rounds):
        last = await chat_completion_messages(messages=messages, temperature=0.35, max_tokens=6000)
        tools = parse_fox_tools(last)
        if tools is None:
            return last
        tool_payload = await run_tool_calls(session, principal, tools)
        messages.append({"role": "assistant", "content": last})
        messages.append(
            {
                "role": "user",
                "content": "Tool results (JSON, for you only):\n"
                + json.dumps(tool_payload, ensure_ascii=False),
            }
        )
    return last or "The assistant stopped after too many tool rounds; try a narrower question."


def _sse(event: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode()


async def run_assistant_stream(
    session: AsyncSession,
    principal: Principal,
    *,
    history: list[tuple[str, str]],
    max_llm_rounds: int = 8,
) -> AsyncIterator[bytes]:
    """Server-sent events: ``delta`` (text chunk), ``done``, ``error``."""
    from foxengine.services.llm_client import (
        LlmError,
        LlmUnavailableError,
        chat_completion_messages_stream,
    )

    messages = _history_to_messages(history)
    if len(messages) <= 1:
        yield _sse({"type": "delta", "text": "Send a message first."})
        yield _sse({"type": "done"})
        return

    try:
        for _ in range(max_llm_rounds):
            buf = ""
            mode: str | None = None
            async for piece in chat_completion_messages_stream(
                messages=messages,
                temperature=0.35,
                max_tokens=6000,
            ):
                buf += piece
                if mode is None:
                    lead = buf.lstrip()
                    if not lead:
                        continue
                    if lead[0] == "{":
                        mode = "hold_json"
                    else:
                        mode = "stream_text"
                        yield _sse({"type": "delta", "text": buf})
                    continue
                if mode == "hold_json":
                    continue
                yield _sse({"type": "delta", "text": piece})

            if mode is None:
                if buf.strip():
                    yield _sse({"type": "delta", "text": buf.strip()})
                else:
                    yield _sse({"type": "delta", "text": "Empty model response."})
                yield _sse({"type": "done"})
                return

            if mode == "hold_json":
                tools = parse_fox_tools(buf)
                if tools:
                    messages.append({"role": "assistant", "content": buf})
                    tool_payload = await run_tool_calls(session, principal, tools)
                    messages.append(
                        {
                            "role": "user",
                            "content": "Tool results (JSON, for you only):\n"
                            + json.dumps(tool_payload, ensure_ascii=False),
                        }
                    )
                    continue
                for i in range(0, len(buf), 48):
                    yield _sse({"type": "delta", "text": buf[i : i + 48]})
                yield _sse({"type": "done"})
                return

            yield _sse({"type": "done"})
            return

        yield _sse({"type": "delta", "text": "Too many tool rounds; try a narrower question."})
        yield _sse({"type": "done"})
    except LlmUnavailableError as e:
        yield _sse({"type": "error", "message": str(e)})
        yield _sse({"type": "done"})
    except LlmError as e:
        yield _sse({"type": "error", "message": str(e)})
        yield _sse({"type": "done"})
    except Exception as e:
        yield _sse({"type": "error", "message": str(e)})
        yield _sse({"type": "done"})
