"""Authentication, RBAC, device pairing and secret encryption."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from pathlib import Path

import jwt
from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer

JWT_SECRET = os.getenv("JWT_SECRET") or secrets.token_urlsafe(48)
TOKEN_TTL = int(os.getenv("TOKEN_TTL_SECONDS", "3600"))
DEVICE_TOKEN_TTL = int(os.getenv("DEVICE_TOKEN_TTL_SECONDS", str(30 * 24 * 3600)))
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}

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


def issue_token(user: str, role: str, ttl: int = TOKEN_TTL, device_id: str | None = None) -> str:
    claims = {"sub": user, "role": role, "exp": int(time.time()) + ttl}
    if device_id:
        claims["dev"] = device_id
    return jwt.encode(claims, JWT_SECRET, algorithm="HS256")


def is_local(request: Request) -> bool:
    return bool(request.client) and request.client.host in LOCAL_HOSTS


def current_user(request: Request, token: str | None = Depends(oauth2)) -> dict:
    # Single-user desktop mode skips sign-in ONLY for requests from this computer. Phones and other
    # machines on the network must always present a token.
    if os.getenv("AUTH_DISABLED", "false").lower() == "true" and is_local(request) and not token:
        return {"user": "local", "role": "trader"}
    if not token:
        raise HTTPException(401, "not authenticated")
    try:
        p = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"invalid token: {e}") from e
    if p.get("dev") and not devices.is_active(p["dev"]):
        raise HTTPException(401, "this device has been unpaired")
    return {"user": p["sub"], "role": p["role"], "device": p.get("dev")}


def require(perm: str):
    def dep(u: dict = Depends(current_user)) -> dict:
        if perm not in PERMISSIONS.get(u["role"], set()):
            raise HTTPException(403, f"role '{u['role']}' lacks permission '{perm}'")
        return u
    return dep


class DeviceRegistry:
    """Phones paired with this desktop. A pairing code is 6 digits, single-use, valid 5 minutes and
    locked after 5 wrong attempts. Paired devices get a long-lived token that can be revoked here."""

    def __init__(self, path: str | None = None):
        self.path = Path(path or os.getenv("PAIRED_DEVICES", "data/devices.json"))
        self.pending: dict | None = None

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self, d: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(d, indent=2))

    def start(self, role: str = "trader") -> dict:
        code = f"{secrets.randbelow(10**6):06d}"
        self.pending = {"hash": hashlib.sha256(code.encode()).hexdigest(), "expires": time.time() + 300,
                        "attempts": 0, "role": role}
        return {"code": code, "expires_in_seconds": 300}

    def claim(self, code: str, device_name: str) -> dict:
        p = self.pending
        if not p or time.time() > p["expires"]:
            raise PermissionError("no active pairing code; generate a new one on the desktop")
        p["attempts"] += 1
        if p["attempts"] > 5:
            self.pending = None
            raise PermissionError("too many attempts; generate a new code")
        if not hmac.compare_digest(hashlib.sha256(code.strip().encode()).hexdigest(), p["hash"]):
            raise PermissionError("wrong code")
        self.pending = None
        dev_id = uuid.uuid4().hex[:12]
        d = self._load()
        d[dev_id] = {"name": device_name[:60] or "Phone", "role": p["role"], "paired_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        self._save(d)
        return {"device_id": dev_id, "role": p["role"],
                "access_token": issue_token(f"device:{device_name[:30]}", p["role"], DEVICE_TOKEN_TTL, dev_id)}

    def list(self) -> dict:
        return self._load()

    def revoke(self, dev_id: str) -> bool:
        d = self._load()
        if d.pop(dev_id, None) is None:
            return False
        self._save(d)
        return True

    def is_active(self, dev_id: str) -> bool:
        return dev_id in self._load()


devices = DeviceRegistry()


class SecretBox:
    """Encrypts brokerage tokens at rest (Fernet / AES-128-CBC + HMAC). The key comes from the OS keychain
    via the desktop app, or from AWS Secrets Manager in the cloud (GB_ENCRYPTION_KEY)."""

    def __init__(self, key: str | None = None):
        self.f = Fernet(key or os.environ.get("GB_ENCRYPTION_KEY") or Fernet.generate_key())

    def seal(self, plaintext: str) -> str:
        return self.f.encrypt(plaintext.encode()).decode()

    def open(self, token: str) -> str:
        return self.f.decrypt(token.encode()).decode()
