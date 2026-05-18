from foxengine.services.file_hash import sha256_hex


def test_sha256_hex_is_stable() -> None:
    payload = b"same-bytes"
    assert sha256_hex(payload) == sha256_hex(payload)


def test_sha256_hex_changes_with_content() -> None:
    assert sha256_hex(b"one") != sha256_hex(b"two")
