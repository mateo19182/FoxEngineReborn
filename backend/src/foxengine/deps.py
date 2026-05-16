import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from foxengine.db.models import ApiKey, User
from foxengine.db.session import get_session_factory
from foxengine.security import decode_jwt, is_api_key_token


@dataclass
class Principal:
    user_id: UUID
    username: str
    roles: list[str]
    api_key_id: UUID | None


async def get_session() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_principal(
    request: Request,
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "empty token")

    if is_api_key_token(token):
        digest = hashlib.sha256(token.encode()).hexdigest()
        res = await session.execute(
            select(ApiKey).where(ApiKey.key_hash == digest, ApiKey.revoked_at.is_(None))
        )
        row = res.scalar_one_or_none()
        if row is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid api key")
        ures = await session.execute(
            select(User)
            .where(User.id == row.owner_user_id, User.is_active.is_(True))
            .options(selectinload(User.roles))
        )
        user = ures.scalar_one_or_none()
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid api key owner")
        await session.execute(
            update(ApiKey).where(ApiKey.id == row.id).values(last_used_at=datetime.now(UTC))
        )
        await session.commit()
        roles = [r.name for r in user.roles]
        return Principal(user_id=user.id, username=user.username, roles=roles, api_key_id=row.id)

    secret = getattr(request.app.state, "jwt_secret", None)
    if not secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "jwt not configured")
    try:
        payload = decode_jwt(token, secret)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
    user_id = UUID(sub)
    ures = await session.execute(
        select(User)
        .where(User.id == user_id, User.is_active.is_(True))
        .options(selectinload(User.roles))
    )
    user = ures.scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")
    roles = payload.get("roles") or [r.name for r in user.roles]
    if not isinstance(roles, list):
        roles = [r.name for r in user.roles]
    return Principal(
        user_id=user.id,
        username=user.username,
        roles=[str(x) for x in roles],
        api_key_id=None,
    )


def require_roles(*allowed: str):
    async def inner(p: Annotated[Principal, Depends(get_principal)]) -> Principal:
        if not set(p.roles) & set(allowed):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient role")
        return p

    return inner


PrincipalDep = Annotated[Principal, Depends(get_principal)]
AdminDep = Annotated[Principal, Depends(require_roles("admin"))]
OperatorDep = Annotated[Principal, Depends(require_roles("admin", "operator", "manager"))]
ViewerDep = Annotated[
    Principal, Depends(require_roles("admin", "operator", "manager", "viewer"))
]
