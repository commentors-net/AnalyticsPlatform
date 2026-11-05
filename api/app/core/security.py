"""Authentication, Password Hashing, JWT Tokens and API Key Management."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from api.app.core.config import settings

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# HTTP Bearer scheme
security_bearer = HTTPBearer(auto_error=False)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against an encoded hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Generate a bcrypt password hash."""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT access token."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ANALYTICS_ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "iat": now})
    return jwt.encode(to_encode, settings.ANALYTICS_JWT_SECRET, algorithm=settings.ANALYTICS_JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT access token."""
    try:
        payload = jwt.decode(token, settings.ANALYTICS_JWT_SECRET, algorithms=[settings.ANALYTICS_JWT_ALGORITHM])
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def generate_api_key(environment: str) -> Tuple[str, str, str]:
    """Generate a write-only API key for event ingestion.
    
    Returns:
        (raw_key, prefix, key_hash)
        raw_key: Returned to administrator once (e.g. 'apk_live_9f2a4b8c...').
        prefix: Short non-secret identifier for dashboard listing (e.g. 'apk_live_9f2a').
        key_hash: SHA-256 hex digest persisted to PostgreSQL.
    """
    env_str = "live" if environment == "live" else "test"
    random_hex = secrets.token_hex(24)
    raw_key = f"apk_{env_str}_{random_hex}"
    prefix = f"apk_{env_str}_{random_hex[:8]}"
    key_hash = hash_api_key(raw_key)
    return raw_key, prefix, key_hash


def hash_api_key(raw_key: str) -> str:
    """Compute the SHA-256 hash of an API key for secure database storage."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
