"""Authentication, RBAC, and secret encryption."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

import jwt
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

JWT_SECRET = os.getenv("JWT_SECRET") or secrets.token_urlsafe(48)
TOKEN_TTL = int(os.getenv("TOKEN_TTL_SECONDS", "3600"))

# Role-based access control matrix
PERMISSIONS = {
    "admin":   {"read", "research", "propose", "approve", "submit", "broker_connect", "settings", "audit"},
    "trader":  {"read", "research", "propose", "approve", "submit", "broker_connect"},
    "analyst": {"read", "research", "propose"},
    "viewer":  {"read"},
    "agent":   {"read", "research", "propose"},   # AI agents: never approve/submit
}

oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)


def hash_password(pw: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 600_000)
    return salt.hex() + "$" + dk.hex()


def verify_password(pw: str, stored: str) -> bool:
    salt, dk = stored.split("$")
    return hmac.compare_digest(hash_password(pw, bytes.fromhex(salt)).split("$")[1], dk)


def issue_token(user: str, role: str) -> str:
    return jwt.encode({"sub": user, "role": role, "exp": int(time.time()) + TOKEN_TTL}, JWT_SECRET, algorithm="HS256")


def current_user(token: str | None = Depends(oauth2)) -> dict:
    if os.getenv("AUTH_DISABLED", "false").lower() == "true":   # local single-user desktop mode only
        return {"user": "local", "role": "trader"}
    if not token:
        raise HTTPException(401, "not authenticated")
    try:
        p = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"invalid token: {e}") from e
    return {"user": p["sub"], "role": p["role"]}


def require(perm: str):
    def dep(u: dict = Depends(current_user)) -> dict:
        if perm not in PERMISSIONS.get(u["role"], set()):
            raise HTTPException(403, f"role '{u['role']}' lacks permission '{perm}'")
        return u
    return dep


class SecretBox:
    """Encrypts brokerage tokens at rest (Fernet / AES-128-CBC + HMAC). The key comes from the OS keychain
    via the desktop app, or from AWS Secrets Manager in the cloud (GB_ENCRYPTION_KEY)."""

    def __init__(self, key: str | None = None):
        self.f = Fernet(key or os.environ.get("GB_ENCRYPTION_KEY") or Fernet.generate_key())

    def seal(self, plaintext: str) -> str:
        return self.f.encrypt(plaintext.encode()).decode()

    def open(self, token: str) -> str:
        return self.f.decrypt(token.encode()).decode()
