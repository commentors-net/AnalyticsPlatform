"""Google Sign-In OpenID Connect ID Token Verification.

Verifies Google ID tokens server-side using Google's cryptographic certificates,
validating signature, issuer, audience, email verification, and expiration.
"""

import logging
from typing import Optional, Set
from fastapi import HTTPException, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from pydantic import BaseModel, EmailStr

from api.app.core.config import settings

logger = logging.getLogger("analytics_platform.auth")


class GoogleUserInfo(BaseModel):
    sub: str
    email: EmailStr
    email_verified: bool
    name: Optional[str] = None
    picture: Optional[str] = None


def get_allowed_audiences() -> Optional[Set[str]]:
    """Parse configured allowed Google Client IDs / audiences."""
    if not settings.GOOGLE_CLIENT_ID:
        return None
    return {aud.strip() for aud in settings.GOOGLE_CLIENT_ID.split(",") if aud.strip()}


def verify_google_id_token(token_str: str) -> GoogleUserInfo:
    """Verify Google ID token signature, issuer, audience, and expiration.
    
    Raises HTTPException 401 on signature/issuer/audience/expiry failure.
    Raises HTTPException 403 on unverified email address.
    """
    if not token_str or not isinstance(token_str, str) or len(token_str.strip()) < 10:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google ID token format",
        )

    token_str = token_str.strip()

    # 1. Mock / Testing Mode Support
    if settings.USE_MOCK_GOOGLE_AUTH or settings.ENVIRONMENT == "testing":
        if token_str.startswith("mock_google_id_token:"):
            parts = token_str.split(":")
            if len(parts) >= 3:
                email = parts[1].lower().strip()
                sub = parts[2].strip()
                modifier = parts[3].strip() if len(parts) >= 4 else ""

                if modifier == "expired":
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Google ID token has expired",
                    )
                if modifier == "bad_issuer":
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid Google ID token issuer: https://attacker.com",
                    )
                if modifier == "bad_audience":
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Google ID token audience does not match configured Google Client ID",
                    )
                if modifier == "unverified":
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Google account email is not verified",
                    )

                return GoogleUserInfo(
                    sub=sub,
                    email=email,
                    email_verified=True,
                    name="Test Google User",
                )

    # 2. Production Cryptographic Google ID Token Verification
    try:
        request = google_requests.Request()
        allowed_audiences = get_allowed_audiences()

        # If a single audience or None
        audience_param = None
        if allowed_audiences and len(allowed_audiences) == 1:
            audience_param = next(iter(allowed_audiences))

        # Cryptographically verifies signature against Google's public JWKS certificates
        # and verifies expiration (exp)
        claims = id_token.verify_oauth2_token(token_str, request, audience=audience_param)

        # Verify issuer strictly
        issuer = claims.get("iss")
        if issuer not in ("accounts.google.com", "https://accounts.google.com"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid Google ID token issuer: '{issuer}'",
            )

        # Multi-audience validation if multiple configured
        if allowed_audiences and len(allowed_audiences) > 1:
            aud = claims.get("aud")
            if aud not in allowed_audiences:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Google ID token audience '{aud}' not in configured allowed audiences",
                )

        # Verify email presence and verification status
        email = claims.get("email")
        if not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Google ID token does not contain an email claim",
            )

        email_verified = claims.get("email_verified", False)
        if not email_verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Google account email address is not verified",
            )

        sub = claims.get("sub")
        if not sub:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Google ID token missing subject (sub) claim",
            )

        return GoogleUserInfo(
            sub=str(sub),
            email=email.lower().strip(),
            email_verified=True,
            name=claims.get("name"),
            picture=claims.get("picture"),
        )
    except ValueError as val_err:
        logger.warning(f"Google ID token signature/claims verification failed: {val_err}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Google ID token verification failed: {val_err}",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Unexpected error during Google ID token verification: {exc}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Failed to verify Google Identity credentials",
        )
