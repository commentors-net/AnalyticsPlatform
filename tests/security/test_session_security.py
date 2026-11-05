"""Cookie reads, CSRF-bound logout and durable per-token revocation (prompt 14)."""

import hashlib

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.app.core.security import create_access_token
from api.app.main import app
from api.app.services.firestore_repo import FirestoreRepo, get_repo


@pytest_asyncio.fixture
async def secure_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://session.test") as client:
        yield client


async def sign_in(client, user):
    response = await client.post("/api/v1/auth/google", json={
        "id_token": f"mock_google_id_token:{user.email}:session-test-subject",
    })
    assert response.status_code == 200
    return response


@pytest.mark.asyncio
async def test_cookie_reads_restore_session_without_csrf(secure_client, superadmin_user):
    login = await sign_in(secure_client, superadmin_user)
    assert any("HttpOnly" in header and "Secure" in header and "SameSite=lax" in header
               for header in login.headers.get_list("set-cookie"))
    profile = await secure_client.get("/api/v1/auth/me")
    assert profile.status_code == 200
    assert profile.json()["id"] == str(superadmin_user.id)
    assert (await secure_client.get("/api/v1/apps")).status_code == 200
    assert (await secure_client.get("/api/v1/auth/me", headers={"X-CSRF-Token": "irrelevant-on-read"})).status_code == 200


@pytest.mark.parametrize("csrf", [None, "wrong-value"])
@pytest.mark.asyncio
async def test_cookie_logout_requires_valid_csrf(secure_client, superadmin_user, csrf):
    await sign_in(secure_client, superadmin_user)
    response = await secure_client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf} if csrf else {})
    assert response.status_code == 403
    assert (await secure_client.get("/api/v1/auth/me")).status_code == 200


@pytest.mark.asyncio
async def test_matching_forged_cookie_header_cannot_replace_signed_csrf(secure_client, superadmin_user):
    await sign_in(secure_client, superadmin_user)
    secure_client.cookies.set("csrf_token", "forged", domain="session.test", path="/")
    response = await secure_client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "forged"})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_logout_revokes_cookie_and_bearer_replay_across_repositories(secure_client, superadmin_user, db_session):
    login = await sign_in(secure_client, superadmin_user)
    token = login.json()["access_token"]
    csrf = login.json()["csrf_token"]
    response = await secure_client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
    assert not secure_client.cookies.get("access_token")
    assert not secure_client.cookies.get("csrf_token")
    assert (await secure_client.get("/api/v1/auth/me")).status_code == 401

    # Another API instance/repository reads the shared durable record, not local memory state.
    other_repo = FirestoreRepo(db_session.db)
    app.dependency_overrides[get_repo] = lambda: other_repo
    try:
        replay = await secure_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert replay.status_code == 401
        secure_client.cookies.set("access_token", token, domain="session.test", path="/")
        assert (await secure_client.get("/api/v1/auth/me")).status_code == 401
    finally:
        app.dependency_overrides.pop(get_repo, None)

    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    record = db_session.db.users_col.document(str(superadmin_user.id)).collection("revoked_sessions").document(digest).get()
    assert record.exists
    assert set(record.to_dict()) == {"expires_at"}


@pytest.mark.asyncio
async def test_bearer_logout_revokes_only_that_login(secure_client, superadmin_user):
    first = await sign_in(secure_client, superadmin_user)
    second = await sign_in(secure_client, superadmin_user)
    first_token, second_token = first.json()["access_token"], second.json()["access_token"]
    response = await secure_client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {first_token}"})
    assert response.status_code == 200
    assert (await secure_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {first_token}"})).status_code == 401
    assert (await secure_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {second_token}"})).status_code == 200


@pytest.mark.asyncio
async def test_logout_write_failure_does_not_claim_success_or_clear_session(secure_client, superadmin_user, db_session, monkeypatch):
    login = await sign_in(secure_client, superadmin_user)

    def unavailable(*args):
        raise RuntimeError("synthetic persistence failure")

    monkeypatch.setattr(db_session, "revoke_session", unavailable)
    response = await secure_client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": login.json()["csrf_token"]})
    assert response.status_code == 503
    assert not response.headers.get_list("set-cookie")
    assert (await secure_client.get("/api/v1/auth/me")).status_code == 200


@pytest.mark.asyncio
async def test_revocation_lookup_failure_denies_protected_data(secure_client, superadmin_user, db_session, monkeypatch):
    await sign_in(secure_client, superadmin_user)

    def unavailable(*args):
        raise RuntimeError("synthetic persistence failure")

    monkeypatch.setattr(db_session, "is_session_revoked", unavailable)
    assert (await secure_client.get("/api/v1/auth/me")).status_code == 503


@pytest.mark.asyncio
async def test_unauthenticated_logout_is_rejected(secure_client):
    assert (await secure_client.post("/api/v1/auth/logout")).status_code == 401


@pytest.mark.asyncio
async def test_cookie_mutation_requires_signed_csrf_claim(secure_client, superadmin_user):
    token = create_access_token({"sub": str(superadmin_user.id)})
    secure_client.cookies.set("access_token", token, domain="session.test", path="/")
    secure_client.cookies.set("csrf_token", "unsigned", domain="session.test", path="/")
    assert (await secure_client.get("/api/v1/auth/me")).status_code == 200
    response = await secure_client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "unsigned"})
    assert response.status_code == 403
