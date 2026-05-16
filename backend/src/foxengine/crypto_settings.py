from cryptography.fernet import Fernet

from foxengine.config import get_settings


def fernet() -> Fernet:
    return Fernet(get_settings().master_key.encode())


def encrypt_secret(plain: str) -> str:
    return fernet().encrypt(plain.encode()).decode()


def decrypt_secret(token: str) -> str:
    return fernet().decrypt(token.encode()).decode()
