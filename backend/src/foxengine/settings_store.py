from sqlalchemy.ext.asyncio import AsyncSession

from foxengine.crypto_settings import decrypt_secret, encrypt_secret
from foxengine.db.models import Setting

SETUP_KEY = "setup_complete"
JWT_SECRET_KEY = "jwt_signing_secret_enc"


async def is_setup_complete(session: AsyncSession) -> bool:
    r = await session.get(Setting, SETUP_KEY)
    if not r:
        return False
    return bool(r.value.get("v"))


async def mark_setup_complete(session: AsyncSession, user_id) -> None:
    r = await session.get(Setting, SETUP_KEY)
    if r:
        r.value = {"v": True}
        r.updated_by = user_id
        return
    session.add(Setting(key=SETUP_KEY, value={"v": True}, updated_by=user_id))
    await session.flush()


async def read_jwt_secret(session: AsyncSession) -> str | None:
    r = await session.get(Setting, JWT_SECRET_KEY)
    if not r:
        return None
    ct = r.value.get("ciphertext")
    if not ct:
        return None
    return decrypt_secret(ct)


async def write_jwt_secret(session: AsyncSession, plain: str, user_id) -> None:
    r = await session.get(Setting, JWT_SECRET_KEY)
    val = {"ciphertext": encrypt_secret(plain)}
    if r:
        r.value = val
        r.updated_by = user_id
    else:
        session.add(Setting(key=JWT_SECRET_KEY, value=val, updated_by=user_id))
    await session.flush()
