import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from foxengine.config import get_settings

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(password_hash: str, plain: str) -> bool:
    try:
        _hasher.verify(password_hash, plain)
        return True
    except VerifyMismatchError:
        return False


def issue_jwt(user_id: UUID, roles: list[str], secret: str) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    exp = now + timedelta(hours=s.jwt_ttl_hours)
    return jwt.encode(
        {"sub": str(user_id), "roles": roles, "iat": now, "exp": exp},
        secret,
        algorithm="HS256",
    )


def decode_jwt(token: str, secret: str) -> dict:
    return jwt.decode(token, secret, algorithms=["HS256"])


def new_api_key_material() -> tuple[str, str]:
    raw = "fox_" + secrets.token_urlsafe(24)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return raw, digest


def is_api_key_token(token: str) -> bool:
    return token.startswith("fox_")
