"""Password verification and authenticated, password-derived quiz storage."""
from __future__ import annotations

import base64
import binascii
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
TEXT_MAGIC = b"CHDQ1-BASE64"
BANK_SHA256 = "c79db778ec9268f05a8e6876e428905ae9db7ac1a3dd83c52c6288f8dfe3c6ec"


class BankError(ValueError):
    """Safe, actionable resource diagnostics without credentials or quiz data."""


def checked_payload(path=None) -> bytes:
    resource = Path(path) if path is not None else Path(__file__).with_name("chd_bank.enc")
    try:
        payload = resource.read_bytes()
    except FileNotFoundError as error:
        raise BankError("题库文件 chd_bank.enc 缺失，请重新安装完整插件资源") from error
    except PermissionError as error:
        raise BankError("题库文件 chd_bank.enc 无读取权限，请检查文件权限") from error
    except OSError as error:
        raise BankError("题库文件 chd_bank.enc 读取失败，请检查存储或挂载状态") from error
    # MoviePilot installers may download resources as text. ASCII armor keeps
    # the authenticated ciphertext unchanged across UTF-8 and newline conversion.
    text = payload.removeprefix(b"\xef\xbb\xbf").lstrip()
    if text.startswith(TEXT_MAGIC):
        header, separator, body = text.partition(b"\n")
        try:
            if not separator or header.rstrip(b"\r") != TEXT_MAGIC or not body.strip():
                raise ValueError("invalid text envelope")
            payload = base64.b64decode(b"".join(body.split()), validate=True)
        except (binascii.Error, ValueError) as error:
            raise BankError("题库 Base64 文本封装无效或已损坏，请重新安装完整插件资源") from error
    # Legacy binary files remain supported, but lossy UTF-8 conversions must fail.
    actual = hashlib.sha256(payload).hexdigest()
    if not hmac.compare_digest(actual, BANK_SHA256):
        raise BankError(
            "题库完整性校验失败：chd_bank.enc 已损坏、被替换或与当前插件版本不匹配"
            f"（解码后二进制期望 SHA256 {BANK_SHA256}，实际 {actual}）；"
            "请恢复匹配版本的题库或重新安装完整插件资源，无需修改解锁密码或站点 Cookie"
        )
    if not payload.startswith(MAGIC) or len(payload) < len(MAGIC) + 28:
        raise BankError("题库文件封装格式无效，请重新安装完整插件资源")
    return payload


def derive_key(password: str) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), SALT, ITERATIONS)


def unlock(password: str):
    if not isinstance(password, str) or not password:
        return None
    key = derive_key(password)
    digest = hmac.new(key, b"captchasignin/unlock/v1", "sha256").hexdigest()
    return key if hmac.compare_digest(digest, VERIFIER) else None


def read_bank(key: bytes, path=None) -> dict:
    # Validate decoded ciphertext before importing dependencies or decrypting.
    payload = checked_payload(path)
    try:
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as error:
        raise BankError("题库解密依赖 cryptography 缺失或无法加载，请重新安装插件依赖") from error
    offset = len(MAGIC)
    try:
        plain = AESGCM(key).decrypt(payload[offset:offset + 12], payload[offset + 12:], MAGIC)
    except InvalidTag as error:
        raise BankError("题库文件完整性校验通过，但认证解密失败：密钥与资源不匹配，请更新完整插件并重新保存有效解锁配置") from error
    except (TypeError, ValueError) as error:
        raise BankError("题库解密密钥状态无效，请重新保存有效解锁配置") from error
    try:
        bank = json.loads(zlib.decompress(plain))
    except (zlib.error, ValueError, UnicodeError) as error:
        raise BankError("题库解密后数据解析失败，请重新安装完整插件资源") from error
    if (not isinstance(bank, dict) or bank.get("version") != 1
            or not isinstance(bank.get("records"), dict) or not bank["records"]):
        raise BankError("题库数据版本或结构无效，请更新匹配的完整插件资源")
    return bank["records"]


def bank_problem(key=None) -> str:
    """Inspect current resources, including decryption when already unlocked."""
    try:
        if key is None:
            checked_payload()
        else:
            read_bank(key)
    except BankError as error:
        return str(error)
    return ""
