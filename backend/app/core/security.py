"""令牌、哈希、加密。

- 登录令牌：32 字节随机串，库里只存 SHA-256。
- 手机号、身份证号：AES-GCM 加密存储；另存 HMAC 哈希用于查找和比对，不可反推。
- 后台密码：Argon2。
"""

import hashlib
import hmac
import os
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

_ph = PasswordHasher()


def _derive(purpose: str) -> bytes:
    return hashlib.sha256(f"{purpose}:{settings.secret_key}".encode()).digest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def keyed_hash(value: str, purpose: str) -> str:
    """带密钥的哈希：同样的手机号得到同样的值，用来查重；没有密钥无法反推。"""
    return hmac.new(_derive(f"hmac:{purpose}"), value.encode(), hashlib.sha256).hexdigest()


def encrypt(plain: str, purpose: str) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(_derive(f"aes:{purpose}")).encrypt(nonce, plain.encode(), None)


def decrypt(blob: bytes, purpose: str) -> str:
    return AESGCM(_derive(f"aes:{purpose}")).decrypt(blob[:12], blob[12:], None).decode()


def sign(value: str) -> str:
    """给下载链接之类的短期 URL 签名。"""
    return hmac.new(_derive("url-sign"), value.encode(), hashlib.sha256).hexdigest()[:32]


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except VerificationError:
        return False
    except Exception:
        # 演示数据里的占位哈希不是合法的 Argon2 格式
        return False


def mask_phone(phone: str) -> str:
    return phone[:3] + "****" + phone[-4:] if len(phone) >= 7 else "****"
