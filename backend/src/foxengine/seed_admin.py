"""Optional first admin from JSON seed (Docker / scripted installs)."""

from __future__ import annotations

import json
import logging
import secrets
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from foxengine.db.models import Role, User, UserRole
from foxengine.security import hash_password
from foxengine.settings_store import mark_setup_complete, write_jwt_secret

log = logging.getLogger(__name__)


def default_admin_seed_path() -> Path:
    return Path(__file__).resolve().parents[2] / "seeds" / "initial_admin.json"


async def ensure_admin_from_seed(session: AsyncSession) -> None:
    path = default_admin_seed_path()
    if not path.is_file():
        return
    n = await session.scalar(select(func.count()).select_from(User))
    if int(n or 0) > 0:
        return
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    username = str(data["username"]).strip()
    password = str(data["password"])
    if not username or not password:
        msg = "admin seed: username and password must be non-empty"
        raise ValueError(msg)
    admin_role = (
        await session.execute(select(Role).where(Role.name == "admin"))
    ).scalar_one_or_none()
    if admin_role is None:
        msg = "admin seed: admin role missing"
        raise RuntimeError(msg)
    user = User(username=username, password_hash=hash_password(password))
    session.add(user)
    await session.flush()
    session.add(UserRole(user_id=user.id, role_id=admin_role.id))
    jwt_secret = secrets.token_urlsafe(48)
    await write_jwt_secret(session, jwt_secret, user.id)
    await mark_setup_complete(session, user.id)
    await session.commit()
    log.info(
        "applied admin seed for user %r (remove or edit %s after first deploy)",
        username,
        path,
    )
