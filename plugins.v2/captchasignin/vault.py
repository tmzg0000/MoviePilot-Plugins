"""Password verification and authenticated, password-derived quiz storage."""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import zlib

# Only a salt and one-way verifier are distributed; the decryption key is supplied
# by the user's password and is never embedded in the plugin or its data file.
SALT = bytes.fromhex("c4e8a59d613fbe7c205a970f4dcb1832")
ITERATIONS = 600_000
VERIFIER = "0eb993e0c733700b3cbd90f244aba8baf86d08a0aeb277b08b4223e426e9b75f"
MAGIC = b"CHDQ1"


def derive_key(password: str) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), SALT, ITERATIONS)


def unlock(password: str):
    if not isinstance(password, str) or not password:
        return None
    key = derive_key(password)
    digest = hmac.new(key, b"captchasignin/unlock/v1", "sha256").hexdigest()
    return key if hmac.compare_digest(digest, VERIFIER) else None


def read_bank(key: bytes, path=None) -> dict:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    payload = Path(path or Path(__file__).with_name("chd_bank.enc")).read_bytes()
    if not payload.startswith(MAGIC) or len(payload) < len(MAGIC) + 28:
        raise ValueError("题库数据格式无效")
    offset = len(MAGIC)
    plain = AESGCM(key).decrypt(payload[offset:offset + 12], payload[offset + 12:], MAGIC)
    bank = json.loads(zlib.decompress(plain))
    if not isinstance(bank, dict) or bank.get("version") != 1 or not isinstance(bank.get("records"), dict):
        raise ValueError("题库数据版本无效")
    return bank["records"]
