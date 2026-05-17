import io
import json
import re
import secrets
import time
from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import aioboto3
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from foxengine import schemas
from foxengine.audit_log import schedule_audit
from foxengine.clickhouse import get_ch_client
from foxengine.config import get_settings
from foxengine.db.models import (
    ApiKey,
    AuditLog,
    Batch,
    IngestRejection,
    Job,
    Role,
    Tag,
    User,
    UserRole,
)
from foxengine.deps import AdminDep, OperatorDep, PrincipalDep, SessionDep, ViewerDep
from foxengine.security import hash_password, issue_jwt, new_api_key_material, verify_password
from foxengine.services.archive_unpack import merge_text_parts, unpack_archive
from foxengine.services.assistant_chat import run_assistant_stream, run_assistant_turn
from foxengine.services.column_map_llm import suggest_column_map_with_llm
from foxengine.services.format_detect import (
    CANONICAL,
    CANONICAL_FIELDS,
    analyze_text_payload,
    detect_for_ingest,
)
from foxengine.services.ingest import ingest_sync
from foxengine.services.job_queries import compile_leads_where, leads_select_sql
from foxengine.services.llm_client import LlmError, LlmUnavailableError, llm_health_status
from foxengine.services.nl_to_dsl import translate_nl_to_dsl
from foxengine.services.related_rows import annotate_related_groups, collect_identity_values
from foxengine.settings_store import (
    is_setup_complete,
    mark_setup_complete,
    read_jwt_secret,
    write_jwt_secret,
)
from foxengine.tag_taxonomy import taxonomy_payload
from foxengine.tasks import foxengine_bulk_tag, foxengine_export, foxengine_ingest_file

router = APIRouter()

_BATCH_INGEST_PREFIX = re.compile(
    r"^uploads/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$"
)
_EXPORT_JOB_PREFIX = re.compile(
    r"^exports/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})/$"
)


def _audit(
    request: Request,
    principal,
    action: str,
    *,
    target_kind: str | None = None,
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    actor_kind = "api_key" if principal.api_key_id else "user"
    schedule_audit(
        actor_id=principal.user_id,
        actor_kind=actor_kind,
        api_key_id=principal.api_key_id,
        action=action,
        target_kind=target_kind,
        target_id=target_id,
        details=details,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


@router.get("/health")
async def health(request: Request, session: SessionDep) -> dict[str, Any]:
    out: dict[str, Any] = {
        "postgres": "unknown",
        "clickhouse": "unknown",
        "object_store": "unknown",
        "llm": "unknown",
    }
    try:
        await session.execute(select(1))
        out["postgres"] = "ok"
    except Exception as e:
        out["postgres"] = f"error: {e!s}"
    try:
        ch = await get_ch_client()
        await ch.query("SELECT 1")
        out["clickhouse"] = "ok"
    except Exception as e:
        out["clickhouse"] = f"error: {e!s}"
    try:
        import aioboto3

        s = get_settings()
        session_boto = aioboto3.Session()
        async with session_boto.client(
            "s3",
            endpoint_url=s.s3_endpoint_url,
            aws_access_key_id=s.s3_access_key_id,
            aws_secret_access_key=s.s3_secret_access_key,
            region_name=s.s3_region,
        ) as c:
            await c.list_buckets()
        out["object_store"] = "ok"
    except Exception as e:
        out["object_store"] = f"error: {e!s}"
    out["llm"] = await llm_health_status()
    return out


@router.get("/setup/status", response_model=schemas.SetupStatusResponse)
async def setup_status(session: SessionDep) -> schemas.SetupStatusResponse:
    n = await session.scalar(select(func.count()).select_from(User))
    return schemas.SetupStatusResponse(needs_setup=int(n or 0) == 0)


@router.post("/setup/complete", response_model=schemas.SetupCompleteResponse)
async def setup_complete(
    request: Request,
    body: schemas.SetupCompleteRequest,
    session: SessionDep,
) -> schemas.SetupCompleteResponse:
    n = await session.scalar(select(func.count()).select_from(User))
    if int(n or 0) > 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "setup already completed")
    admin_role = (
        await session.execute(select(Role).where(Role.name == "admin"))
    ).scalar_one_or_none()
    if admin_role is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "admin role missing")
    user = User(
        username=body.username.strip(),
        password_hash=hash_password(body.password),
    )
    session.add(user)
    await session.flush()
    session.add(UserRole(user_id=user.id, role_id=admin_role.id))
    raw, digest = new_api_key_material()
    session.add(ApiKey(name="initial", key_hash=digest, owner_user_id=user.id))
    jwt_secret = secrets.token_urlsafe(48)
    await write_jwt_secret(session, jwt_secret, user.id)
    await mark_setup_complete(session, user.id)
    await session.commit()
    request.app.state.jwt_secret = jwt_secret
    schedule_audit(
        actor_id=user.id,
        actor_kind="user",
        api_key_id=None,
        action="setup.finish",
        details={"username": user.username},
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return schemas.SetupCompleteResponse(
        api_key=raw,
        message="store the API key securely; it is shown only once",
    )


@router.post("/auth/login", response_model=schemas.LoginResponse)
async def login(
    request: Request,
    body: schemas.LoginRequest,
    session: SessionDep,
) -> schemas.LoginResponse:
    if not await is_setup_complete(session):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "setup not finished")
    secret = await read_jwt_secret(session)
    if not secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "jwt secret missing")
    res = await session.execute(select(User).where(User.username == body.username))
    user = res.scalar_one_or_none()
    if user is None or not verify_password(user.password_hash, body.password):
        schedule_audit(
            actor_id=None,
            actor_kind="system",
            api_key_id=None,
            action="auth.login.failure",
            details={"username": body.username},
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        await session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "disabled")
    await session.execute(
        update(User).where(User.id == user.id).values(last_login_at=datetime.now(UTC))
    )
    await session.refresh(user, ["roles"])
    roles = [r.name for r in user.roles]
    token = issue_jwt(user.id, roles, secret)
    schedule_audit(
        actor_id=user.id,
        actor_kind="user",
        api_key_id=None,
        action="auth.login.success",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await session.commit()
    return schemas.LoginResponse(access_token=token)


@router.get("/auth/me", response_model=schemas.MeResponse)
async def me(principal: PrincipalDep) -> schemas.MeResponse:
    s = get_settings()
    return schemas.MeResponse(
        id=str(principal.user_id),
        username=principal.username,
        roles=principal.roles,
        llm_nl_enabled=s.llm_enabled,
    )


@router.post("/auth/password")
async def change_password(
    request: Request,
    body: schemas.PasswordChangeRequest,
    session: SessionDep,
    principal: PrincipalDep,
) -> dict[str, str]:
    res = await session.execute(select(User).where(User.id == principal.user_id))
    user = res.scalar_one()
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "current password incorrect")
    await session.execute(
        update(User)
        .where(User.id == user.id)
        .values(password_hash=hash_password(body.new_password))
    )
    _audit(request, principal, "auth.password_change")
    await session.commit()
    return {"status": "ok"}


@router.get("/users", response_model=list[schemas.UserOut])
async def list_users(session: SessionDep, _: AdminDep) -> list[schemas.UserOut]:
    res = await session.execute(
        select(User).options(selectinload(User.roles)).order_by(User.username)
    )
    users = res.scalars().unique().all()
    return [
        schemas.UserOut(
            id=str(u.id),
            username=u.username,
            email=u.email,
            is_active=u.is_active,
            roles=[r.name for r in u.roles],
        )
        for u in users
    ]


@router.post("/users", response_model=schemas.UserOut)
async def create_user(
    request: Request,
    body: schemas.UserCreateRequest,
    session: SessionDep,
    admin: AdminDep,
) -> schemas.UserOut:
    role_rows = (
        await session.execute(select(Role).where(Role.name.in_(body.roles)))
    ).scalars().all()
    if len(role_rows) != len(set(body.roles)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown role in list")
    user = User(
        username=body.username.strip(),
        email=body.email.strip() if body.email else None,
        password_hash=hash_password(body.password),
        created_by=admin.user_id,
    )
    session.add(user)
    await session.flush()
    for rr in role_rows:
        session.add(UserRole(user_id=user.id, role_id=rr.id))
    await session.commit()
    await session.refresh(user, ["roles"])
    _audit(
        request,
        admin,
        "user.create",
        target_kind="user",
        target_id=str(user.id),
        details={"username": user.username},
    )
    return schemas.UserOut(
        id=str(user.id),
        username=user.username,
        email=user.email,
        is_active=user.is_active,
        roles=[r.name for r in user.roles],
    )


def _audit_ts_param(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@router.get("/audit-log/actions", response_model=list[str])
async def audit_log_distinct_actions(session: SessionDep, _: AdminDep) -> list[str]:
    res = await session.execute(select(AuditLog.action).distinct().order_by(AuditLog.action.asc()))
    return [str(x) for x in res.scalars().all()]


@router.get("/audit-log", response_model=schemas.AuditLogListResponse)
async def audit_log_list(
    session: SessionDep,
    _: AdminDep,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    actions: list[str] | None = Query(default=None),
    actor_id: UUID | None = None,
    action_contains: str | None = Query(default=None, max_length=128),
    ts_from: datetime | None = None,
    ts_to: datetime | None = None,
) -> schemas.AuditLogListResponse:
    ts_lo = _audit_ts_param(ts_from) if ts_from is not None else None
    ts_hi = _audit_ts_param(ts_to) if ts_to is not None else None
    if ts_lo is not None and ts_hi is not None and ts_lo > ts_hi:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "ts_from must be before or equal to ts_to",
        )
    conditions: list[Any] = []
    if actions:
        conditions.append(AuditLog.action.in_(tuple(actions)))
    if actor_id is not None:
        conditions.append(AuditLog.actor_id == actor_id)
    if action_contains is not None and (frag := action_contains.strip()):
        conditions.append(AuditLog.action.ilike(f"%{frag}%"))
    if ts_lo is not None:
        conditions.append(AuditLog.ts >= ts_lo)
    if ts_hi is not None:
        conditions.append(AuditLog.ts <= ts_hi)

    count_stmt = select(func.count()).select_from(AuditLog)
    list_stmt = (
        select(AuditLog, User.username)
        .outerjoin(User, AuditLog.actor_id == User.id)
        .order_by(AuditLog.ts.desc())
        .limit(limit)
        .offset(offset)
    )
    if conditions:
        count_stmt = count_stmt.where(*conditions)
        list_stmt = list_stmt.where(*conditions)

    total = int(await session.scalar(count_stmt) or 0)
    res = await session.execute(list_stmt)
    items: list[schemas.AuditLogEntry] = []
    for log_row, actor_username in res.all():
        ip_s = log_row.ip
        if ip_s is not None:
            ip_s = str(ip_s)
        items.append(
            schemas.AuditLogEntry(
                id=int(log_row.id),
                ts=log_row.ts.isoformat(),
                actor_kind=log_row.actor_kind,
                actor_username=actor_username,
                action=log_row.action,
                target_kind=log_row.target_kind,
                target_id=log_row.target_id,
                details=dict(log_row.details or {}),
                ip=ip_s,
                user_agent=log_row.user_agent,
            )
        )
    return schemas.AuditLogListResponse(total=total, items=items)


@router.get("/api-keys", response_model=list[schemas.ApiKeyOut])
async def list_keys(session: SessionDep, principal: PrincipalDep) -> list[schemas.ApiKeyOut]:
    q = select(ApiKey).where(ApiKey.revoked_at.is_(None))
    if "admin" not in principal.roles:
        q = q.where(ApiKey.owner_user_id == principal.user_id)
    res = await session.execute(q.order_by(ApiKey.created_at.desc()))
    keys = res.scalars().all()
    return [
        schemas.ApiKeyOut(
            id=str(k.id),
            name=k.name,
            created_at=k.created_at.isoformat(),
            last_used_at=k.last_used_at.isoformat() if k.last_used_at else None,
            revoked_at=k.revoked_at.isoformat() if k.revoked_at else None,
        )
        for k in keys
    ]


@router.post("/api-keys", response_model=schemas.ApiKeyCreateResponse)
async def create_key(
    request: Request,
    body: schemas.ApiKeyCreateRequest,
    session: SessionDep,
    principal: PrincipalDep,
) -> schemas.ApiKeyCreateResponse:
    raw, digest = new_api_key_material()
    row = ApiKey(name=body.name, key_hash=digest, owner_user_id=principal.user_id)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    _audit(
        request,
        principal,
        "api_key.create",
        target_kind="api_key",
        target_id=str(row.id),
        details={"name": row.name},
    )
    return schemas.ApiKeyCreateResponse(id=str(row.id), name=row.name, key=raw)


@router.delete("/api-keys/{key_id}")
async def revoke_key(
    request: Request,
    key_id: UUID,
    session: SessionDep,
    principal: PrincipalDep,
) -> dict[str, str]:
    res = await session.execute(select(ApiKey).where(ApiKey.id == key_id))
    row = res.scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    if row.owner_user_id != principal.user_id and "admin" not in principal.roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not owner")
    await session.execute(
        update(ApiKey).where(ApiKey.id == key_id).values(revoked_at=datetime.now(UTC))
    )
    await session.commit()
    _audit(
        request,
        principal,
        "api_key.revoke",
        target_kind="api_key",
        target_id=str(key_id),
    )
    return {"status": "ok"}


@router.get("/tags/taxonomy", response_model=schemas.TagTaxonomyOut)
async def tag_taxonomy(_: ViewerDep) -> schemas.TagTaxonomyOut:
    return schemas.TagTaxonomyOut.model_validate(taxonomy_payload())


@router.get("/tags", response_model=list[schemas.TagOut])
async def list_tags(session: SessionDep, _: ViewerDep) -> list[schemas.TagOut]:
    res = await session.execute(
        select(Tag).where(Tag.deleted_at.is_(None)).order_by(Tag.name)
    )
    rows = res.scalars().all()
    return [schemas.TagOut.from_tag(t) for t in rows]


@router.post("/tags", response_model=schemas.TagOut)
async def create_tag(
    request: Request,
    body: schemas.TagCreate,
    session: SessionDep,
    principal: OperatorDep,
) -> schemas.TagOut:
    bd: date | None = None
    if body.breach_date:
        bd = date.fromisoformat(body.breach_date)
    tag = Tag(
        name=body.name.strip(),
        source_url=body.source_url,
        breach_date=bd,
        type=body.type,
        notes=body.notes,
        created_by=principal.user_id,
    )
    session.add(tag)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "could not create tag (duplicate name?)",
        ) from None
    await session.refresh(tag)
    _audit(
        request,
        principal,
        "tag.create",
        target_kind="tag",
        target_id=str(tag.id),
        details={"name": str(tag.name)},
    )
    return schemas.TagOut.from_tag(tag)


@router.patch("/tags/{tag_id}", response_model=schemas.TagOut)
async def patch_tag(
    request: Request,
    tag_id: UUID,
    body: schemas.TagPatch,
    session: SessionDep,
    principal: OperatorDep,
) -> schemas.TagOut:
    res = await session.execute(select(Tag).where(Tag.id == tag_id, Tag.deleted_at.is_(None)))
    tag = res.scalar_one_or_none()
    if tag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    if body.name is not None:
        tag.name = body.name.strip()
    if body.source_url is not None:
        tag.source_url = body.source_url
    if body.breach_date is not None:
        tag.breach_date = date.fromisoformat(body.breach_date) if body.breach_date else None
    if "type" in body.model_fields_set:
        tag.type = body.type
    if body.notes is not None:
        tag.notes = body.notes
    await session.commit()
    await session.refresh(tag)
    _audit(request, principal, "tag.update", target_kind="tag", target_id=str(tag_id))
    return schemas.TagOut.from_tag(tag)


@router.delete("/tags/{tag_id}")
async def delete_tag(
    request: Request,
    tag_id: UUID,
    session: SessionDep,
    principal: AdminDep,
) -> dict[str, str]:
    res = await session.execute(select(Tag).where(Tag.id == tag_id, Tag.deleted_at.is_(None)))
    tag = res.scalar_one_or_none()
    if tag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    await session.execute(
        update(Tag).where(Tag.id == tag_id).values(deleted_at=datetime.now(UTC))
    )
    await session.commit()
    _audit(request, principal, "tag.delete", target_kind="tag", target_id=str(tag_id))
    return {"status": "ok"}


@router.post("/index")
async def index(
    request: Request,
    body: schemas.IndexRequest,
    session: SessionDep,
    principal: OperatorDep,
) -> dict[str, Any]:
    ch = await get_ch_client()
    try:
        result = await ingest_sync(
            session,
            ch,
            principal,
            body.leads,
            body.tag_names,
            body.batch_name,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    _audit(
        request,
        principal,
        "batch.ingest.done",
        target_kind="batch",
        target_id=result["batch_id"],
        details=result,
    )
    return result


@router.post("/query")
async def run_query(
    request: Request,
    body: schemas.QueryRequest,
    session: SessionDep,
    principal: ViewerDep,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        where_sql, params = await compile_leads_where(session, body.dsl)
    except Exception as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid dsl: {e}") from e

    ch = await get_ch_client()
    settings_ch = {
        "max_execution_time": 60,
        "max_result_rows": 1000,
        "max_memory_usage": "4000000000",
    }
    count_sql = f"SELECT count() FROM leads WHERE {where_sql}"

    cnt = (await ch.query(count_sql, parameters=params, settings=settings_ch)).first_row[0]
    data_sql = leads_select_sql(where_sql, limit=body.limit, offset=body.offset)
    qr = await ch.query(data_sql, parameters=params, settings=settings_ch)
    out_rows = [dict(r) for r in qr.named_results()]
    if body.view == "related" and out_rows:
        identity_values = collect_identity_values(out_rows)
        related_params = dict(params)
        related_params.update(
            {
                "rel_emails": identity_values["email_norm"],
                "rel_phones": identity_values["phone_norm"],
                "rel_usernames": identity_values["username"],
                "rel_id_cards": identity_values["id_card"],
            }
        )
        s = get_settings()
        related_where_sql = (
            "has({rel_emails:Array(String)}, email_norm) "
            "OR has({rel_phones:Array(String)}, phone_norm) "
            "OR has({rel_usernames:Array(String)}, lower(username)) "
            "OR has({rel_id_cards:Array(String)}, id_card) "
        )
        related_sql = leads_select_sql(related_where_sql, limit=s.related_rows_cap)
        related_settings_ch = {**settings_ch, "max_result_rows": int(s.related_rows_cap)}
        related_qr = await ch.query(
            related_sql,
            parameters=related_params,
            settings=related_settings_ch,
        )
        by_key: dict[tuple[str, int], dict[str, Any]] = {}
        matched_keys: set[tuple[str, int]] = set()
        for row in out_rows:
            key = (str(row["batch_id"]), int(row["row_in_batch"]))
            matched_keys.add(key)
            by_key[key] = row
        for row in (dict(r) for r in related_qr.named_results()):
            key = (str(row["batch_id"]), int(row["row_in_batch"]))
            by_key.setdefault(key, row)
        out_rows = annotate_related_groups(list(by_key.values()), matched_keys)
    ms = int((time.perf_counter() - t0) * 1000)
    _audit(
        request,
        principal,
        "query.run",
        details={
            "query": body.dsl,
            "dsl": body.dsl,
            "view": body.view,
            "limit": body.limit,
            "offset": body.offset,
            "duration_ms": ms,
            "result_count": len(out_rows),
            "total_matching": int(cnt),
        },
    )
    return {
        "total": int(cnt),
        "rows": out_rows,
        "limit": body.limit,
        "offset": body.offset,
        "view": body.view,
    }


@router.post("/query/nl", response_model=schemas.QueryNlResponse)
async def translate_query_nl(
    request: Request,
    body: schemas.QueryNlRequest,
    session: SessionDep,
    principal: ViewerDep,
) -> schemas.QueryNlResponse:
    if not get_settings().llm_enabled:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "NL translation is disabled on this instance (FOX_LLM_ENABLED=false).",
        )
    try:
        result = await translate_nl_to_dsl(session, body.nl)
    except LlmUnavailableError as e:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            str(e),
        ) from e
    out = schemas.QueryNlResponse.model_validate(cast(dict[str, Any], result))
    _audit(
        request,
        principal,
        "query.nl_translate",
        details={
            "ok": out.ok,
            "nl_len": len(body.nl),
            "dsl": out.dsl,
            "error": out.error,
        },
    )
    return out


@router.post("/assistant/chat", response_model=schemas.AssistantChatResponse)
async def assistant_chat(
    request: Request,
    body: schemas.AssistantChatRequest,
    session: SessionDep,
    principal: ViewerDep,
) -> schemas.AssistantChatResponse:
    if not get_settings().llm_enabled:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Assistant is disabled on this instance (FOX_LLM_ENABLED=false).",
        )
    history: list[tuple[str, str]] = [(m.role, m.content) for m in body.messages]
    try:
        reply = await run_assistant_turn(session, principal, history=history)
    except LlmUnavailableError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    except LlmError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    _audit(
        request,
        principal,
        "assistant.chat",
        details={
            "turns": len(body.messages),
            "reply_len": len(reply),
        },
    )
    return schemas.AssistantChatResponse(reply=reply)


@router.post("/assistant/chat/stream")
async def assistant_chat_stream(
    request: Request,
    body: schemas.AssistantChatRequest,
    session: SessionDep,
    principal: ViewerDep,
) -> StreamingResponse:
    if not get_settings().llm_enabled:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Assistant is disabled on this instance (FOX_LLM_ENABLED=false).",
        )
    history: list[tuple[str, str]] = [(m.role, m.content) for m in body.messages]

    async def gen():
        try:
            async for chunk in run_assistant_stream(session, principal, history=history):
                yield chunk
        except Exception as e:
            err = json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)
            yield f"data: {err}\n\n".encode()
            done = json.dumps({"type": "done"}, ensure_ascii=False)
            yield f"data: {done}\n\n".encode()

    _audit(
        request,
        principal,
        "assistant.chat",
        details={"stream": True, "turns": len(body.messages)},
    )
    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid download uri")
    rest = uri.removeprefix("s3://")
    bucket, sep, key = rest.partition("/")
    if sep == "" or not key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid download uri")
    return bucket, key


def _can_view_job(principal, job: Job) -> bool:
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


def _form_bool(v: str) -> bool:
    return v.strip().lower() in ("1", "true", "yes", "on")


def _parse_column_map_json(column_map_json: str | None) -> tuple[bool, dict[str, str]]:
    if column_map_json is None or not column_map_json.strip():
        return False, {}
    try:
        parsed = json.loads(column_map_json)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "column_map_json must be a JSON object"
        ) from e
    if not isinstance(parsed, dict):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "column_map_json must be a JSON object",
        )

    out: dict[str, str] = {}
    for raw_header, raw_field in parsed.items():
        header = str(raw_header).strip()
        field = str(raw_field).strip()
        if not header:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "column_map_json headers must be non-empty strings",
            )
        if field not in CANONICAL:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"unknown canonical field in column_map_json: {field}",
            )
        out[header] = field
    return True, out


def _coerce_column_map(raw: dict[Any, Any], *, label: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw_header, raw_field in raw.items():
        header = str(raw_header).strip()
        field = str(raw_field).strip()
        if not header:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{label} headers must be non-empty strings",
            )
        if field not in CANONICAL:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"unknown canonical field in {label}: {field}",
            )
        out[header] = field
    return out


def _parse_column_map_by_file_json(
    column_map_by_file_json: str | None,
) -> tuple[bool, dict[str, dict[str, str]]]:
    if column_map_by_file_json is None or not column_map_by_file_json.strip():
        return False, {}
    try:
        parsed = json.loads(column_map_by_file_json)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "column_map_by_file_json must be an object of {filename: column_map}",
        ) from e
    if not isinstance(parsed, dict):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "column_map_by_file_json must be an object of {filename: column_map}",
        )

    out: dict[str, dict[str, str]] = {}
    for raw_name, raw_map in parsed.items():
        inner_name = str(raw_name)
        if not isinstance(raw_map, dict):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "column_map_by_file_json values must be JSON objects",
            )
        out[inner_name] = _coerce_column_map(raw_map, label="column_map_by_file_json")
    return True, out


def _inner_storage_key(inner_name: str) -> str:
    return inner_name.replace("/", "_").replace("\\", "_")[:220]


def _preview_file_payload(
    inner_name: str,
    blob: bytes,
    *,
    staging_key: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    d = analyze_text_payload(inner_name, blob)
    preview = {
        "inner_name": inner_name,
        "format": d.format,
        "format_confidence": d.format_confidence,
        "csv_delimiter": d.csv_delimiter,
        "headers": d.headers,
        "column_guesses": d.column_guesses,
        "recommended_column_map": d.recommended_column_map,
        "sample_rows": d.sample_rows[:10],
        "size": len(blob),
    }
    staged = {
        "inner_name": inner_name,
        "staging_key": staging_key,
        "size": len(blob),
        "format": d.format,
        "detect_confidence": d.format_confidence,
        "csv_delimiter": d.csv_delimiter or ",",
        "column_map": dict(d.recommended_column_map) if d.format == "csv" else {},
    }
    return preview, staged


def _upload_checkpoint_parts(upload: Job) -> list[dict[str, Any]]:
    raw_parts = dict(upload.checkpoint or {}).get("parts")
    if not isinstance(raw_parts, list):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "upload preview is missing file parts")
    parts: list[dict[str, Any]] = []
    for raw in raw_parts:
        if isinstance(raw, dict):
            parts.append(raw)
    return parts


def _selected_upload_parts(
    upload: Job,
    selected_files: list[str],
) -> list[dict[str, Any]]:
    parts = _upload_checkpoint_parts(upload)
    by_name = {str(part.get("inner_name")): part for part in parts if part.get("inner_name")}
    if selected_files:
        selected: list[dict[str, Any]] = []
        for name in selected_files:
            part = by_name.get(name)
            if part is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown selected file: {name}")
            selected.append(part)
        return selected
    return parts


def _normalize_storage_prefix(store: schemas.StorageStore, raw: str) -> str:
    p = raw.strip().lstrip("/")
    if ".." in p or "//" in p:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid prefix")
    root = "uploads/" if store == "uploads" else "exports/"
    if not p:
        return root
    need = "uploads/" if store == "uploads" else "exports/"
    if not p.startswith(need):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"prefix must start with {need}",
        )
    return p if p.endswith("/") else f"{p}/"


def _storage_object_key_allowed(store: schemas.StorageStore, key: str) -> bool:
    k = key.strip().lstrip("/")
    if ".." in k or "//" in k:
        return False
    if store == "uploads":
        return k.startswith("uploads/")
    return k.startswith("exports/")


def _storage_browse_child_name(parent_prefix: str, child_prefix: str) -> str:
    rest = child_prefix[len(parent_prefix) :].rstrip("/")
    return rest.split("/")[-1]


def _bucket_for_store(s, store: schemas.StorageStore) -> str:
    if store == "uploads":
        return s.s3_bucket_uploads
    return s.s3_bucket_exports


async def _tag_names_for_batch(session: AsyncSession, batch_id: UUID) -> list[str]:
    ch = await get_ch_client()
    qr = await ch.query(
        "SELECT groupUniqArray(tag_id) AS ids "
        "FROM lead_tags WHERE batch_id = {bid:UUID}",
        parameters={"bid": batch_id},
    )
    row = qr.first_row
    if not row or row[0] is None:
        return []
    ids_raw = row[0]
    if not ids_raw:
        return []
    tag_uuids: list[UUID] = []
    for x in ids_raw:
        if x is None:
            continue
        try:
            tag_uuids.append(UUID(str(x)))
        except ValueError:
            continue
    if not tag_uuids:
        return []
    res = await session.execute(
        select(Tag.name).where(Tag.id.in_(tag_uuids), Tag.deleted_at.is_(None)).order_by(Tag.name)
    )
    return [str(n) for n in res.scalars().all()]


async def _storage_folder_context(
    session: AsyncSession,
    store: schemas.StorageStore,
    normalized_prefix: str,
) -> schemas.StorageFolderContext:
    if store == "uploads":
        m = _BATCH_INGEST_PREFIX.match(normalized_prefix)
        if not m:
            return schemas.StorageFolderContext()
        bid = UUID(m.group(1))
        b = await session.scalar(select(Batch).where(Batch.id == bid, Batch.deleted_at.is_(None)))
        tags = await _tag_names_for_batch(session, bid)
        if b is None:
            return schemas.StorageFolderContext(
                kind="ingest_batch",
                batch_id=str(bid),
                tag_names=tags,
            )
        return schemas.StorageFolderContext(
            kind="ingest_batch",
            batch_id=str(b.id),
            batch_name=b.name,
            source_filename=b.source_filename,
            tag_names=tags,
        )
    m = _EXPORT_JOB_PREFIX.match(normalized_prefix)
    if not m:
        return schemas.StorageFolderContext()
    jid = UUID(m.group(1))
    j = await session.scalar(select(Job).where(Job.id == jid))
    if j is None:
        return schemas.StorageFolderContext(
            kind="export_job",
            job_id=str(jid),
        )
    ck = dict(j.checkpoint or {})
    dsl = ck.get("dsl")
    dsl_s = str(dsl).strip() if isinstance(dsl, str) else None
    return schemas.StorageFolderContext(
        kind="export_job",
        job_id=str(j.id),
        job_type=j.type,
        job_state=j.state,
        export_dsl=dsl_s,
        export_rows=int(j.processed_rows),
    )


@router.get("/storage/browse", response_model=schemas.StorageBrowseResponse)
async def storage_browse(
    session: SessionDep,
    _: OperatorDep,
    store: schemas.StorageStore = Query("uploads"),
    prefix: str = Query("", description="Prefix within the chosen store (uploads/… or exports/…)"),
) -> schemas.StorageBrowseResponse:
    normalized = _normalize_storage_prefix(store, prefix)
    s = get_settings()
    bucket = _bucket_for_store(s, store)
    entries: list[schemas.UploadBrowseEntry] = []
    session_boto = aioboto3.Session()
    async with session_boto.client(
        "s3",
        endpoint_url=s.s3_endpoint_url,
        aws_access_key_id=s.s3_access_key_id,
        aws_secret_access_key=s.s3_secret_access_key,
        region_name=s.s3_region,
    ) as c:
        resp = await c.list_objects_v2(
            Bucket=bucket,
            Prefix=normalized,
            Delimiter="/",
        )
        for cp in sorted(resp.get("CommonPrefixes") or [], key=lambda x: str(x["Prefix"])):
            full = str(cp["Prefix"])
            entries.append(
                schemas.UploadBrowseEntry(
                    key=_storage_browse_child_name(normalized, full),
                    is_directory=True,
                )
            )
        for obj in sorted(resp.get("Contents") or [], key=lambda x: str(x["Key"])):
            key_full = str(obj["Key"])
            if key_full.endswith("/"):
                continue
            name = key_full[len(normalized) :]
            if not name or "/" in name:
                continue
            lm = obj.get("LastModified")
            entries.append(
                schemas.UploadBrowseEntry(
                    key=name,
                    is_directory=False,
                    size=int(obj["Size"]) if obj.get("Size") is not None else None,
                    content_type=None,
                    last_modified=lm.isoformat() if lm is not None else None,
                )
            )
    folder = await _storage_folder_context(session, store, normalized)
    return schemas.StorageBrowseResponse(
        store=store,
        prefix=normalized,
        entries=entries,
        folder=folder,
    )


@router.get("/storage/presign", response_model=schemas.StoragePresignResponse)
async def storage_presign(
    request: Request,
    principal: OperatorDep,
    store: schemas.StorageStore = Query("uploads"),
    key: str = Query(..., min_length=1, description="Full object key within the chosen store"),
) -> schemas.StoragePresignResponse:
    raw = key.strip().lstrip("/")
    if not _storage_object_key_allowed(store, raw):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid key")
    s = get_settings()
    bucket = _bucket_for_store(s, store)
    session_boto = aioboto3.Session()
    async with session_boto.client(
        "s3",
        endpoint_url=s.s3_endpoint_url,
        aws_access_key_id=s.s3_access_key_id,
        aws_secret_access_key=s.s3_secret_access_key,
        region_name=s.s3_region,
    ) as c:
        url = await c.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": raw},
            ExpiresIn=3600,
        )
    _audit(
        request,
        principal,
        "storage.presign",
        details={"store": store, "key": raw},
    )
    return schemas.StoragePresignResponse(url=url)


@router.get("/batches", response_model=list[schemas.BatchOut])
async def list_batches(session: SessionDep, _: ViewerDep) -> list[schemas.BatchOut]:
    res = await session.execute(
        select(Batch).where(Batch.deleted_at.is_(None)).order_by(Batch.ingest_ts.desc()).limit(200)
    )
    rows = res.scalars().all()
    return [
        schemas.BatchOut(
            id=str(b.id),
            name=b.name,
            source_filename=b.source_filename,
            accepted_rows=int(b.accepted_rows),
            rejected_rows=int(b.rejected_rows),
            duplicate_rows=int(b.duplicate_rows),
            ingest_ts=b.ingest_ts.isoformat(),
        )
        for b in rows
    ]


@router.get("/batches/{batch_id}", response_model=schemas.BatchOut)
async def get_batch(batch_id: UUID, session: SessionDep, _: ViewerDep) -> schemas.BatchOut:
    res = await session.execute(
        select(Batch).where(Batch.id == batch_id, Batch.deleted_at.is_(None))
    )
    b = res.scalar_one_or_none()
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    return schemas.BatchOut(
        id=str(b.id),
        name=b.name,
        source_filename=b.source_filename,
        accepted_rows=int(b.accepted_rows),
        rejected_rows=int(b.rejected_rows),
        duplicate_rows=int(b.duplicate_rows),
        ingest_ts=b.ingest_ts.isoformat(),
    )


@router.get("/batches/{batch_id}/rejections.csv")
async def batch_rejections_csv(
    batch_id: UUID,
    session: SessionDep,
    _: ViewerDep,
) -> StreamingResponse:
    import csv as csv_mod

    res = await session.execute(
        select(IngestRejection)
        .where(IngestRejection.batch_id == batch_id)
        .order_by(IngestRejection.id)
    )
    rows = res.scalars().all()
    buf = io.StringIO()
    w = csv_mod.writer(buf)
    w.writerow(["line_no", "reason", "raw_line"])
    for r in rows:
        w.writerow([r.line_no or "", r.reason, r.raw_line])
    body = buf.getvalue().encode("utf-8")
    return StreamingResponse(
        iter([body]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="rejections-{batch_id}.csv"'},
    )


@router.get("/jobs", response_model=list[schemas.JobOut])
async def list_jobs(session: SessionDep, principal: PrincipalDep) -> list[schemas.JobOut]:
    q = select(Job).where(Job.type != "ingest_upload").order_by(Job.updated_at.desc()).limit(100)
    if "admin" not in principal.roles:
        q = q.where(Job.owner_user_id == principal.user_id)
    res = await session.execute(q)
    jobs = res.scalars().all()

    batch_ids = [j.batch_id for j in jobs if j.batch_id]
    batch_map: dict[UUID, Batch] = {}
    if batch_ids:
        batch_res = await session.execute(
            select(Batch).where(Batch.id.in_(batch_ids))
        )
        batch_map = {b.id: b for b in batch_res.scalars().all()}

    return [_job_out(j, batch_map[j.batch_id] if j.batch_id is not None else None) for j in jobs]


@router.get("/jobs/{job_id}", response_model=schemas.JobOut)
async def get_job(job_id: UUID, session: SessionDep, principal: PrincipalDep) -> schemas.JobOut:
    res = await session.execute(select(Job).where(Job.id == job_id))
    job = res.scalar_one_or_none()
    if job is None or not _can_view_job(principal, job):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    batch = None
    if job.batch_id:
        batch_res = await session.execute(select(Batch).where(Batch.id == job.batch_id))
        batch = batch_res.scalar_one_or_none()
    return _job_out(job, batch)


@router.get("/jobs/{job_id}/download")
async def download_job_result(
    request: Request,
    job_id: UUID,
    session: SessionDep,
    principal: ViewerDep,
) -> StreamingResponse:
    res = await session.execute(select(Job).where(Job.id == job_id))
    job = res.scalar_one_or_none()
    if job is None or not _can_view_job(principal, job):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    if job.state != "done" or not job.result_uri:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "download not available")

    bucket, key = _parse_s3_uri(job.result_uri)
    s = get_settings()

    async def gen():
        session_boto = aioboto3.Session()
        async with session_boto.client(
            "s3",
            endpoint_url=s.s3_endpoint_url,
            aws_access_key_id=s.s3_access_key_id,
            aws_secret_access_key=s.s3_secret_access_key,
            region_name=s.s3_region,
        ) as c:
            obj = await c.get_object(Bucket=bucket, Key=key)
            stream = obj["Body"]
            while True:
                chunk = await stream.read(65536)
                if not chunk:
                    break
                yield chunk

    action = "export.download" if job.type == "export" else "job.download"
    _audit(request, principal, action, target_kind="job", target_id=str(job_id))
    await session.commit()
    return StreamingResponse(
        gen(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="job-{job_id}"'},
    )


@router.post("/export")
async def start_export(
    request: Request,
    body: schemas.ExportRequest,
    session: SessionDep,
    principal: ViewerDep,
) -> dict[str, str]:
    ckpt: dict[str, object] = {"dsl": body.dsl, "format": body.format}
    if body.row_limit is not None:
        ckpt["row_limit"] = body.row_limit
    job = Job(
        type="export",
        state="queued",
        owner_user_id=principal.user_id,
        checkpoint=ckpt,
    )
    session.add(job)
    await session.flush()
    _audit(
        request,
        principal,
        "export.start",
        target_kind="job",
        target_id=str(job.id),
        details={
            "dsl": body.dsl,
            "format": body.format,
            **({"row_limit": body.row_limit} if body.row_limit is not None else {}),
        },
    )
    await session.commit()
    await foxengine_export.defer_async(job_id=str(job.id))
    return {"job_id": str(job.id)}


@router.post("/ingest/preview")
async def ingest_preview(
    request: Request,
    session: SessionDep,
    principal: OperatorDep,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    data = await file.read()
    outer_fn = file.filename or "upload.bin"
    parts = unpack_archive(outer_fn, data)

    upload_id = uuid4()
    s = get_settings()
    staged_parts: list[dict[str, Any]] = []
    files_out: list[dict[str, Any]] = []
    session_boto = aioboto3.Session()
    async with session_boto.client(
        "s3",
        endpoint_url=s.s3_endpoint_url,
        aws_access_key_id=s.s3_access_key_id,
        aws_secret_access_key=s.s3_secret_access_key,
        region_name=s.s3_region,
    ) as c:
        for idx, (inner_name, blob) in enumerate(parts):
            safe = _inner_storage_key(inner_name)
            key = f"uploads/staged/{upload_id}/{idx:04d}-{safe}"
            await c.put_object(Bucket=s.s3_bucket_uploads, Key=key, Body=blob)
            preview, staged = _preview_file_payload(inner_name, blob, staging_key=key)
            files_out.append(preview)
            staged_parts.append(staged)

    upload = Job(
        id=upload_id,
        type="ingest_upload",
        state="done",
        owner_user_id=principal.user_id,
        processed_rows=len(staged_parts),
        checkpoint={
            "outer_filename": outer_fn,
            "parts": staged_parts,
            "total_size": len(data),
        },
        finished_at=datetime.now(UTC),
    )
    session.add(upload)
    _audit(
        request,
        principal,
        "ingest.upload.preview",
        target_kind="job",
        target_id=str(upload_id),
        details={
            "outer_filename": outer_fn,
            "count": len(staged_parts),
            "total_size": len(data),
        },
    )
    await session.commit()
    return {
        "upload_id": str(upload_id),
        "outer_filename": outer_fn,
        "merge_archive": False,
        "file_count": len(parts),
        "canonical_fields": list(CANONICAL_FIELDS),
        "files": files_out,
    }


@router.post("/ingest/suggest-column-map", response_model=schemas.ColumnMapSuggestResponse)
async def ingest_suggest_column_map(
    _: OperatorDep,
    body: schemas.ColumnMapSuggestRequest,
) -> schemas.ColumnMapSuggestResponse:
    try:
        column_map = await suggest_column_map_with_llm(
            headers=body.headers,
            sample_rows=body.sample_rows,
            inner_name=body.inner_name,
        )
    except LlmUnavailableError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    except LlmError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return schemas.ColumnMapSuggestResponse(
        column_map=column_map,
        canonical_fields=list(CANONICAL_FIELDS),
    )


@router.post("/ingest/file/from-upload")
async def ingest_file_from_upload(
    request: Request,
    body: schemas.IngestQueuedUploadRequest,
    session: SessionDep,
    principal: OperatorDep,
) -> dict[str, Any]:
    try:
        upload_id = UUID(body.upload_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid upload_id") from e

    res = await session.execute(select(Job).where(Job.id == upload_id))
    upload = res.scalar_one_or_none()
    if (
        upload is None
        or upload.type != "ingest_upload"
        or not _can_view_job(principal, upload)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "upload not found")

    tags = [x.strip() for x in body.tag_names.split(",") if x.strip()]
    user_maps_by_file_provided, user_maps_by_file = _parse_column_map_by_file_json(
        body.column_map_by_file_json
    )
    selected_parts = _selected_upload_parts(upload, body.selected_files)
    if not selected_parts:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "choose at least one file to ingest")

    outer_fn = str(dict(upload.checkpoint or {}).get("outer_filename") or "upload.bin")
    s = get_settings()
    items_out: list[dict[str, Any]] = []
    session_boto = aioboto3.Session()
    async with session_boto.client(
        "s3",
        endpoint_url=s.s3_endpoint_url,
        aws_access_key_id=s.s3_access_key_id,
        aws_secret_access_key=s.s3_secret_access_key,
        region_name=s.s3_region,
    ) as c:
        parts_to_queue = selected_parts
        if body.merge_archive and len(selected_parts) > 1:
            blobs: list[tuple[str, bytes]] = []
            for part in selected_parts:
                inner_name = str(part.get("inner_name") or "")
                staging_key = str(part.get("staging_key") or "")
                if not inner_name or not staging_key:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid staged upload part")
                obj = await c.get_object(Bucket=s.s3_bucket_uploads, Key=staging_key)
                blobs.append((inner_name, await obj["Body"].read()))
            merged_name, merged_blob = merge_text_parts(blobs)
            merged_key = f"uploads/staged/{upload_id}/merged-{_inner_storage_key(merged_name)}"
            await c.put_object(Bucket=s.s3_bucket_uploads, Key=merged_key, Body=merged_blob)
            resolved_fmt, detect_extras = detect_for_ingest(merged_name, merged_blob, "auto")
            parts_to_queue = [
                {
                    "inner_name": merged_name,
                    "staging_key": merged_key,
                    "size": len(merged_blob),
                    "format": resolved_fmt,
                    "detect_confidence": detect_extras.get("detect_confidence"),
                    "csv_delimiter": detect_extras.get("csv_delimiter", ","),
                    "column_map": detect_extras.get("column_map", {}),
                }
            ]

        for part in parts_to_queue:
            inner_name = str(part.get("inner_name") or "")
            staging_key = str(part.get("staging_key") or "")
            if not inner_name or not staging_key:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid staged upload part")

            raw_fmt = part.get("format")
            if not isinstance(raw_fmt, str):
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "staged upload part is missing format",
                )
            resolved_fmt = raw_fmt
            if resolved_fmt not in ("jsonl", "csv", "combo"):
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"unsupported format {resolved_fmt!r}",
                )

            auto_map = part.get("column_map")
            merged_map: dict[str, str] = {}
            column_map_source = "auto"
            if (
                user_maps_by_file_provided
                and inner_name in user_maps_by_file
                and resolved_fmt == "csv"
            ):
                merged_map.update(user_maps_by_file[inner_name])
                column_map_source = "manual"
            elif isinstance(auto_map, dict):
                merged_map.update({str(k): str(v) for k, v in auto_map.items()})

            batch_id = uuid4()
            job_id = uuid4()
            safe = _inner_storage_key(inner_name)
            key = f"uploads/{batch_id}/{safe}"
            await c.copy_object(
                Bucket=s.s3_bucket_uploads,
                Key=key,
                CopySource={"Bucket": s.s3_bucket_uploads, "Key": staging_key},
            )

            if len(parts_to_queue) == 1 and not body.merge_archive:
                display_name = body.batch_name or outer_fn
            else:
                base = body.batch_name or outer_fn
                display_name = f"{base} — {inner_name}"

            batch = Batch(
                id=batch_id,
                name=display_name,
                source_filename=inner_name,
                upload_uri=f"s3://{s.s3_bucket_uploads}/{key}",
                ingested_by=principal.user_id,
            )
            job = Job(
                id=job_id,
                type="ingest_file",
                state="queued",
                batch_id=batch_id,
                owner_user_id=principal.user_id,
                checkpoint={
                    "s3_key": key,
                    "format": resolved_fmt,
                    "tag_names": tags,
                    "column_map": merged_map,
                    "column_map_source": column_map_source,
                    "csv_delimiter": part.get("csv_delimiter"),
                    "detect_confidence": part.get("detect_confidence"),
                    "source_upload_id": str(upload_id),
                },
            )
            session.add(batch)
            session.add(job)
            await session.flush()
            items_out.append(
                {
                    "batch_id": str(batch_id),
                    "job_id": str(job_id),
                    "inner_name": inner_name,
                    "format": resolved_fmt,
                    "detect_confidence": part.get("detect_confidence"),
                }
            )

    _audit(
        request,
        principal,
        "batch.upload",
        target_kind="batch",
        target_id=items_out[0]["batch_id"] if items_out else "",
        details={
            "outer_filename": outer_fn,
            "upload_id": str(upload_id),
            "merge_archive": body.merge_archive,
            "count": len(items_out),
            "formats": [x["format"] for x in items_out],
        },
    )
    _audit(
        request,
        principal,
        "batch.ingest.start",
        target_kind="batch",
        target_id=items_out[0]["batch_id"] if items_out else "",
        details={"job_ids": [x["job_id"] for x in items_out]},
    )
    await session.commit()
    for it in items_out:
        await foxengine_ingest_file.defer_async(job_id=it["job_id"])
    if len(items_out) == 1:
        return {
            "batch_id": items_out[0]["batch_id"],
            "job_id": items_out[0]["job_id"],
            "items": items_out,
        }
    return {"items": items_out}


@router.post("/ingest/file")
async def ingest_file(
    request: Request,
    session: SessionDep,
    principal: OperatorDep,
    file: UploadFile = File(...),
    format: str = Form("auto"),
    tag_names: str = Form(""),
    batch_name: str | None = Form(default=None),
    column_map_json: str | None = Form(default=None),
    column_map_by_file_json: str | None = Form(default=None),
    merge_archive: str = Form("false"),
) -> dict[str, Any]:
    fmt_in = format.strip().lower()
    if fmt_in not in ("auto", "jsonl", "csv", "combo"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "format must be auto, jsonl, csv, or combo",
        )
    tags = [x.strip() for x in tag_names.split(",") if x.strip()]
    user_column_map_provided, user_column_map = _parse_column_map_json(column_map_json)
    user_maps_by_file_provided, user_maps_by_file = _parse_column_map_by_file_json(
        column_map_by_file_json
    )

    data = await file.read()
    outer_fn = file.filename or "upload.bin"
    parts = unpack_archive(outer_fn, data)
    merge = _form_bool(merge_archive)
    if merge and len(parts) > 1:
        parts = [merge_text_parts(parts)]

    s = get_settings()
    items_out: list[dict[str, Any]] = []
    session_boto = aioboto3.Session()
    async with session_boto.client(
        "s3",
        endpoint_url=s.s3_endpoint_url,
        aws_access_key_id=s.s3_access_key_id,
        aws_secret_access_key=s.s3_secret_access_key,
        region_name=s.s3_region,
    ) as c:
        for inner_name, blob in parts:
            try:
                resolved_fmt, detect_extras = detect_for_ingest(inner_name, blob, fmt_in)
            except ValueError as e:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
            auto_map = detect_extras.get("column_map")
            merged_map: dict[str, str] = {}
            column_map_source = "auto"
            manual_map: dict[str, str] | None = None
            if user_maps_by_file_provided and inner_name in user_maps_by_file:
                manual_map = user_maps_by_file[inner_name]
            elif user_column_map_provided:
                manual_map = user_column_map

            if manual_map is not None and resolved_fmt == "csv":
                merged_map.update(manual_map)
                column_map_source = "manual"
            elif isinstance(auto_map, dict):
                merged_map.update({str(k): str(v) for k, v in auto_map.items()})

            batch_id = uuid4()
            job_id = uuid4()
            safe = _inner_storage_key(inner_name)
            key = f"uploads/{batch_id}/{safe}"
            await c.put_object(Bucket=s.s3_bucket_uploads, Key=key, Body=blob)

            if len(parts) == 1 and not merge:
                display_name = batch_name or outer_fn
            else:
                base = batch_name or outer_fn
                display_name = f"{base} — {inner_name}"

            batch = Batch(
                id=batch_id,
                name=display_name,
                source_filename=inner_name,
                upload_uri=f"s3://{s.s3_bucket_uploads}/{key}",
                ingested_by=principal.user_id,
            )
            job = Job(
                id=job_id,
                type="ingest_file",
                state="queued",
                batch_id=batch_id,
                owner_user_id=principal.user_id,
                checkpoint={
                    "s3_key": key,
                    "format": resolved_fmt,
                    "tag_names": tags,
                    "column_map": merged_map,
                    "column_map_source": column_map_source,
                    "csv_delimiter": detect_extras.get("csv_delimiter", ","),
                    "detect_confidence": detect_extras.get("detect_confidence"),
                },
            )
            session.add(batch)
            session.add(job)
            await session.flush()
            items_out.append(
                {
                    "batch_id": str(batch_id),
                    "job_id": str(job_id),
                    "inner_name": inner_name,
                    "format": resolved_fmt,
                    "detect_confidence": detect_extras.get("detect_confidence"),
                }
            )

    _audit(
        request,
        principal,
        "batch.upload",
        target_kind="batch",
        target_id=items_out[0]["batch_id"] if items_out else "",
        details={
            "outer_filename": outer_fn,
            "merge_archive": merge,
            "count": len(items_out),
            "formats": [x["format"] for x in items_out],
        },
    )
    _audit(
        request,
        principal,
        "batch.ingest.start",
        target_kind="batch",
        target_id=items_out[0]["batch_id"] if items_out else "",
        details={"job_ids": [x["job_id"] for x in items_out]},
    )
    await session.commit()
    for it in items_out:
        await foxengine_ingest_file.defer_async(job_id=it["job_id"])
    if len(items_out) == 1:
        return {
            "batch_id": items_out[0]["batch_id"],
            "job_id": items_out[0]["job_id"],
            "items": items_out,
        }
    return {"items": items_out}


@router.post("/tags/bulk-apply")
async def bulk_apply_tags(
    request: Request,
    session: SessionDep,
    principal: OperatorDep,
    file: UploadFile = File(...),
    tag_names: str = Form(...),
) -> dict[str, str]:
    tags = [x.strip() for x in tag_names.split(",") if x.strip()]
    if not tags:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "tag_names required")

    job_id = uuid4()
    key = f"uploads/bulk_tag/{job_id}.csv"
    data = await file.read()
    s = get_settings()
    session_boto = aioboto3.Session()
    async with session_boto.client(
        "s3",
        endpoint_url=s.s3_endpoint_url,
        aws_access_key_id=s.s3_access_key_id,
        aws_secret_access_key=s.s3_secret_access_key,
        region_name=s.s3_region,
    ) as c:
        await c.put_object(Bucket=s.s3_bucket_uploads, Key=key, Body=data)

    job = Job(
        id=job_id,
        type="bulk_tag",
        state="queued",
        owner_user_id=principal.user_id,
        checkpoint={
            "s3_key": key,
            "tag_names": tags,
            "owner_user_id": str(principal.user_id),
        },
    )
    session.add(job)
    await session.flush()
    _audit(
        request,
        principal,
        "tag.bulk_apply.start",
        target_kind="job",
        target_id=str(job_id),
        details={"tags": tags},
    )
    await session.commit()
    await foxengine_bulk_tag.defer_async(job_id=str(job_id))
    return {"job_id": str(job_id)}
