"""
Auth service: password hashing and JWT creation/verification.
Uses bcrypt directly (no passlib) to avoid passlib/bcrypt version conflicts.
Default role is faculty; all APIs scope by user_id.
"""
from datetime import datetime, timedelta
from uuid import UUID
import bcrypt
from jose import JWTError, jwt
from app.config import settings

# Bcrypt limit is 72 bytes; use 71 so we never exceed
BCRYPT_MAX_BYTES = 71


def _truncate_to_bytes(s: str, max_bytes: int = BCRYPT_MAX_BYTES) -> bytes:
    """Truncate string to at most max_bytes UTF-8; return bytes for bcrypt."""
    if not s:
        return b""
    encoded = s.encode("utf-8")
    if len(encoded) <= max_bytes:
        return encoded
    return encoded[:max_bytes]


def hash_password(password: str) -> str:
    """Hash password for storage. Raises ValueError if password is None."""
    if password is None:
        raise ValueError("password is required")
    raw = _truncate_to_bytes(password)
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(raw, salt)
    return hashed.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    raw = _truncate_to_bytes(plain)
    try:
        return bcrypt.checkpw(raw, hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: UUID, email: str, role: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=settings.jwt_expire_hours)
    # JWT exp must be numeric (Unix timestamp), not datetime
    payload = {"sub": str(user_id), "email": email, "role": role, "exp": int(expire.timestamp())}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
