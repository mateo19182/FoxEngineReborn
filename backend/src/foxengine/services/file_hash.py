import hashlib


def sha256_hex(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()
