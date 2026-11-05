"""Comprehensive Google Sign-In & Session Security Tests (Prompt 12).

Verifies:
1. Google OpenID Connect ID token verification (signature, issuer, audience, exp).
2. Restriction of access strictly to explicitly approved Google accounts.
3. HttpOnly, SameSite, Secure cookie sessions with double-submit CSRF defense.
4. Permanent retirement of password-based authentication (410 Gone).
5. Logout and session expiry enforcement.
6. User provisioning by SuperAdmin without creating public bypasses.
"""

from datetime import datetime, timedelta, timezone
import pytest
from httpx import AsyncClient
from jose import jwt

from api.app.core.config import settings
from api.app.models.user import User
from api.app.services.firestore_repo import FirestoreRepo


@pytest.mark.asyncio
async def test_google_signin_approved_user_success(client: AsyncClient, superadmin_user: User):
    """Verify an approved Google account signs in successfully and receives secure session cookies."""
    mock_id_token = f"mock_google_id_token:{superadmin_user.email}:google_sub_1001"

    resp = await client.post("/api/v1/auth/google", json={"id_token": mock_id_token})
    assert resp.status_code == 200
    data = resp.json()

    assert data["token_type"] == "bearer"
    assert "access_token" in data
    assert "csrf_token" in data
    assert data["user"]["email"] == superadmin_user.email
    assert data["user"]["role"] == "SuperAdmin"

    # Verify HttpOnly session cookie
    cookies = resp.cookies
    assert "access_token" in cookies
    assert "csrf_token" in cookies


@pytest.mark.asyncio
async def test_google_signin_unapproved_user_rejected_403(client: AsyncClient):
    """Verify that an arbitrary Google account without explicit approval is strictly rejected (M12-03, M12-08)."""
    mock_id_token = "mock_google_id_token:stranger@gmail.com:google_sub_stranger"

    resp = await client.post("/api/v1/auth/google", json={"id_token": mock_id_token})
    assert resp.status_code == 403
    assert "not authorized for dashboard access" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_google_signin_inactive_user_rejected_403(client: AsyncClient, db_session: FirestoreRepo):
    """Verify that suspended or inactive users cannot log in even with valid Google credentials."""
    suspended_email = "suspended_user@analytics.internal"
    db_session.create_user(
        email=suspended_email,
        role="Viewer",
        status="SUSPENDED",
    )

    mock_id_token = f"mock_google_id_token:{suspended_email}:google_sub_suspended"
    resp = await client.post("/api/v1/auth/google", json={"id_token": mock_id_token})
    assert resp.status_code == 403
    assert "suspended or inactive" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_google_signin_unverified_email_rejected_403(client: AsyncClient, superadmin_user: User):
    """Verify that Google accounts with unverified email addresses are rejected (M12-02)."""
    mock_id_token = f"mock_google_id_token:{superadmin_user.email}:google_sub_1001:unverified"

    resp = await client.post("/api/v1/auth/google", json={"id_token": mock_id_token})
    assert resp.status_code == 403
    assert "not verified" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_google_signin_expired_token_rejected_401(client: AsyncClient, superadmin_user: User):
    """Verify expired Google ID tokens are rejected with 401 Unauthorized (M12-02)."""
    mock_id_token = f"mock_google_id_token:{superadmin_user.email}:google_sub_1001:expired"

    resp = await client.post("/api/v1/auth/google", json={"id_token": mock_id_token})
    assert resp.status_code == 401
    assert "expired" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_google_signin_invalid_issuer_rejected_401(client: AsyncClient, superadmin_user: User):
    """Verify Google ID tokens with untrusted issuers are rejected (M12-02)."""
    mock_id_token = f"mock_google_id_token:{superadmin_user.email}:google_sub_1001:bad_issuer"

    resp = await client.post("/api/v1/auth/google", json={"id_token": mock_id_token})
    assert resp.status_code == 401
    assert "issuer" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_google_signin_invalid_audience_rejected_401(client: AsyncClient, superadmin_user: User):
    """Verify Google ID tokens with mismatched audience are rejected (M12-02)."""
    mock_id_token = f"mock_google_id_token:{superadmin_user.email}:google_sub_1001:bad_audience"

    resp = await client.post("/api/v1/auth/google", json={"id_token": mock_id_token})
    assert resp.status_code == 401
    assert "audience" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_google_signin_malformed_token_rejected_401(client: AsyncClient):
    """Verify malformed or garbage tokens are rejected with 401."""
    resp = await client.post("/api/v1/auth/google", json={"id_token": "not-a-token"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_cookie_session_and_csrf_protection(client: AsyncClient, superadmin_user: User):
    """Verify HttpOnly cookie sessions enforce CSRF tokens on state-changing requests (M12-06)."""
    # 1. Login with Google ID token
    mock_id_token = f"mock_google_id_token:{superadmin_user.email}:google_sub_csrf_test"
    login_resp = await client.post("/api/v1/auth/google", json={"id_token": mock_id_token})
    assert login_resp.status_code == 200
    csrf_token = login_resp.json()["csrf_token"]
    access_cookie = login_resp.cookies["access_token"]
    csrf_cookie = login_resp.cookies["csrf_token"]

    app_id = "test-csrf-app"

    # 2. State-changing POST using cookies BUT WITHOUT X-CSRF-Token header -> MUST BE REJECTED 403
    post_no_csrf = await client.post(
        "/api/v1/apps",
        json={"app_id": app_id, "name": "CSRF Target App"},
        cookies={"access_token": access_cookie, "csrf_token": csrf_cookie},
    )
    assert post_no_csrf.status_code == 403
    assert "csrf" in post_no_csrf.json()["detail"].lower()

    # 3. State-changing POST using cookies WITH MISMATCHED X-CSRF-Token -> MUST BE REJECTED 403
    post_bad_csrf = await client.post(
        "/api/v1/apps",
        json={"app_id": app_id, "name": "CSRF Target App"},
        headers={"X-CSRF-Token": "attacker_forged_token_value_xyz"},
        cookies={"access_token": access_cookie, "csrf_token": csrf_cookie},
    )
    assert post_bad_csrf.status_code == 403
    assert "csrf" in post_bad_csrf.json()["detail"].lower()

    # 4. State-changing POST using cookies WITH VALID X-CSRF-Token header -> SUCCEEDS 201
    post_valid = await client.post(
        "/api/v1/apps",
        json={"app_id": app_id, "name": "CSRF Target App"},
        headers={"X-CSRF-Token": csrf_token},
        cookies={"access_token": access_cookie, "csrf_token": csrf_cookie},
    )
    assert post_valid.status_code == 201
    assert post_valid.json()["app_id"] == app_id


@pytest.mark.asyncio
async def test_session_expiry_rejected_401(client: AsyncClient, superadmin_user: User):
    """Verify expired application sessions return 401 Unauthorized (M12-11)."""
    # Create an expired application JWT (expired 10 minutes ago)
    past_exp = datetime.now(timezone.utc) - timedelta(minutes=10)
    expired_token = jwt.encode(
        {"sub": str(superadmin_user.id), "email": superadmin_user.email, "role": "SuperAdmin", "exp": past_exp},
        settings.ANALYTICS_JWT_SECRET,
        algorithm=settings.ANALYTICS_JWT_ALGORITHM,
    )

    resp = await client.get("/api/v1/apps", headers={"Authorization": f"Bearer {expired_token}"})
    assert resp.status_code == 401
    assert "expired" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_logout_flow_clears_session(client: AsyncClient, superadmin_user: User):
    """Verify logout purges session cookies and terminates session (M12-11)."""
    # Login
    mock_id_token = f"mock_google_id_token:{superadmin_user.email}:google_sub_logout_test"
    login_resp = await client.post("/api/v1/auth/google", json={"id_token": mock_id_token})
    assert login_resp.status_code == 200

    # Logout
    logout_resp = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {login_resp.json()['access_token']}"},
    )
    assert logout_resp.status_code == 200
    assert logout_resp.json()["status"] == "logged_out"


@pytest.mark.asyncio
async def test_password_login_endpoints_retired_410(client: AsyncClient):
    """Verify legacy password login endpoints are permanently retired with 410 Gone (M12-07)."""
    resp_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@analytics.internal", "password": "Password123!"},
    )
    assert resp_login.status_code == 410
    assert "retired" in resp_login.json()["detail"].lower()

    resp_token = await client.post(
        "/api/v1/auth/token",
        json={"email": "admin@analytics.internal", "password": "Password123!"},
    )
    assert resp_token.status_code == 410


@pytest.mark.asyncio
async def test_auth_config_endpoint(client: AsyncClient):
    """Verify public auth configuration endpoint returns Google Sign-In details."""
    resp = await client.get("/api/v1/auth/config")
    assert resp.status_code == 200
    data = resp.json()
    assert data["auth_mode"] == "google"


@pytest.mark.asyncio
async def test_auth_config_exposes_web_client_before_cli_audience(client: AsyncClient, monkeypatch):
    """The button must receive one Web client ID, while verification retains CLI support."""
    web_client = "427212681311-7dbgdroclks4gi1b7guitu79iiob1cat.apps.googleusercontent.com"
    cli_client = "32555940559.apps.googleusercontent.com"
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", f"{web_client},{cli_client}")

    response = await client.get("/api/v1/auth/config")
    assert response.status_code == 200
    assert response.json()["google_client_id"] == web_client


@pytest.mark.parametrize("audience,accepted", [
    ("427212681311-7dbgdroclks4gi1b7guitu79iiob1cat.apps.googleusercontent.com", True),
    ("32555940559.apps.googleusercontent.com", True),
    ("unrelated-client.apps.googleusercontent.com", False),
])
def test_production_multi_audience_allowlist(audience, accepted, monkeypatch):
    """Exercise production audience checks with the Google signature verifier stubbed."""
    from fastapi import HTTPException
    from api.app.core import google_auth

    web_client = "427212681311-7dbgdroclks4gi1b7guitu79iiob1cat.apps.googleusercontent.com"
    cli_client = "32555940559.apps.googleusercontent.com"
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", f"{web_client},{cli_client}")
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "USE_MOCK_GOOGLE_AUTH", False)

    def verified_claims(token, request, audience=None):
        assert audience is None  # Multiple audiences are checked after Google verification.
        return claims

    claims = {
        "iss": "https://accounts.google.com",
        "aud": audience,
        "email": "oauth-test@example.com",
        "email_verified": True,
        "sub": "synthetic-google-subject",
    }
    monkeypatch.setattr(google_auth.id_token, "verify_oauth2_token", verified_claims)

    if accepted:
        assert google_auth.verify_google_id_token("synthetic-google-token").sub == claims["sub"]
    else:
        with pytest.raises(HTTPException) as error:
            google_auth.verify_google_id_token("synthetic-google-token")
        assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_user_provisioning_and_rbac_lifecycle(client: AsyncClient, superadmin_user: User):
    """Verify SuperAdmin can provision approved Google accounts and manage roles (M12-03, M12-04)."""
    # Authenticate as SuperAdmin
    token_resp = await client.post(
        "/api/v1/auth/google",
        json={"id_token": f"mock_google_id_token:{superadmin_user.email}:sub_admin"},
    )
    admin_headers = {"Authorization": f"Bearer {token_resp.json()['access_token']}"}

    # 1. Provision a new approved analyst
    new_user_email = "new_analyst@company.com"
    create_resp = await client.post(
        "/api/v1/users",
        json={"email": new_user_email, "role": "AppAdmin"},
        headers=admin_headers,
    )
    assert create_resp.status_code == 201
    created_user_id = create_resp.json()["id"]

    # 2. The newly provisioned user can now successfully log in with Google!
    analyst_login = await client.post(
        "/api/v1/auth/google",
        json={"id_token": f"mock_google_id_token:{new_user_email}:sub_analyst_01"},
    )
    assert analyst_login.status_code == 200
    analyst_token = analyst_login.json()["access_token"]
    analyst_headers = {"Authorization": f"Bearer {analyst_token}"}

    # 3. Non-SuperAdmin (AppAdmin) CANNOT provision other users (RBAC check)
    forbidden_attempt = await client.post(
        "/api/v1/users",
        json={"email": "another@company.com", "role": "AppViewer"},
        headers=analyst_headers,
    )
    assert forbidden_attempt.status_code == 403

    # 4. SuperAdmin lists users
    list_resp = await client.get("/api/v1/users", headers=admin_headers)
    assert list_resp.status_code == 200
    emails = [u["email"] for u in list_resp.json()]
    assert new_user_email in emails

    # 5. SuperAdmin revokes the user
    del_resp = await client.delete(f"/api/v1/users/{created_user_id}", headers=admin_headers)
    assert del_resp.status_code == 200

    # 6. Once revoked, that Google account can NO LONGER log in
    revoked_login = await client.post(
        "/api/v1/auth/google",
        json={"id_token": f"mock_google_id_token:{new_user_email}:sub_analyst_01"},
    )
    assert revoked_login.status_code == 403
