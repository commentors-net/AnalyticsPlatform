"""Only synthetic mock documents are deleted by these tests; never run on live data."""
import copy
import uuid

import pytest

from api.app.core.firestore_db import MockFirestoreClient, MockDocumentReference
from api.app.core.security import create_access_token
from api.app.services import app_deletion


def headers(user):
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id)})}"}


async def preview(client, user, app_id='askanna'):
    response = await client.get(f'/api/v1/apps/{app_id}/deletion-preview', headers=headers(user))
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    return response.json()


async def remove(client, user, data):
    return await client.request('DELETE', f"/api/v1/apps/{data['app_id']}", headers=headers(user),
                                json={'confirmation': data['app_id'], 'preview_token': data['preview_token']})


def seed_related(repo, app_id):
    repo.create_api_key(uuid.uuid4().hex, app_id, 'test', uuid.uuid4().hex, 'apk_test_synthetic', 'Synthetic')
    repo.grant_user_app_permission('synthetic-user', app_id, 'AppAdmin')
    repo.db.idempotency_col.document(uuid.uuid4().hex).set({'app_id': app_id})
    for env in ('live', 'test'):
        repo.db.events_col(app_id, env).document('synthetic-event').set({'app_id': app_id, 'environment': env})
        repo.db.sessions_col(app_id, env).document('synthetic-session').set({'app_id': app_id})
        # Missing intermediate parent documents must not hide nested derived data.
        root = repo.db.client.collection(f'{repo.db.prefix}data').document(f'{app_id}_{env}')
        root.collection('rollups').document('missing-parent').collection('daily').document('synthetic').set({'app_id': app_id})


@pytest.mark.asyncio
async def test_preview_is_read_only_and_delete_cleans_only_exact_app(client, superadmin_user, db_session):
    assert isinstance(db_session.db.client, MockFirestoreClient)
    seed_related(db_session, 'askanna')
    db_session.create_app('askanna-neighbor', 'Neighbor')
    seed_related(db_session, 'askanna-neighbor')
    db_session.db.users_col.document('unrelated-account').set({'sentinel': True})
    db_session.db.client.collection('unrelated_shared_collection').document('sentinel').set({'preserve': True})
    db_session.log_audit('synthetic-admin', 'EXPORT_ANALYTICS', 'application', 'askanna', {})
    before = copy.deepcopy(db_session.db.client._store)
    data = await preview(client, superadmin_user)
    assert data['counts']['live_events'] == 1 and data['counts']['test_events'] == 1
    assert data['counts']['live_rollups'] == 1 and 'audit' in data['retained']
    assert db_session.db.client._store == before
    deleted = await remove(client, superadmin_user, data)
    assert deleted.status_code == 200 and deleted.json()['status'] == 'deleted'
    assert db_session.get_app('askanna') is None
    assert list(app_deletion.inventory(db_session, 'askanna')) == []
    assert db_session.db.deletions_col.document('askanna').get().to_dict()['state'] == 'deleted'
    retried = await remove(client, superadmin_user, data)
    assert retried.status_code == 200 and retried.json()['deleted_this_request'] == 0
    for path, record in before.items():
        if ('askanna-neighbor' in path or record.get('app_id') == 'askanna-neighbor'
                or path.startswith(('analytics_users/', 'unrelated_shared_collection/', 'analytics_audit_logs/'))):
            assert db_session.db.client._store[path] == record
    with pytest.raises(ValueError):
        db_session.create_app('askanna', 'Cannot resurrect')


@pytest.mark.asyncio
async def test_delete_and_preview_are_superadmin_only(client, superadmin_user, db_session):
    data = await preview(client, superadmin_user)
    for role in ('AppViewer', 'AppAdmin'):
        user = db_session.create_user(email=f'{role.lower()}@example.com', role=role)
        db_session.grant_user_app_permission(user['id'], 'askanna', role)
        auth = {'Authorization': f"Bearer {create_access_token({'sub': user['id']})}"}
        assert (await client.get('/api/v1/apps/askanna/deletion-preview', headers=auth)).status_code == 403
        response = await client.request('DELETE', '/api/v1/apps/askanna', headers=auth, json={'confirmation': 'askanna', 'preview_token': data['preview_token']})
        assert response.status_code == 403
    assert (await client.get('/api/v1/apps/askanna/deletion-preview')).status_code == 401
    assert db_session.get_app('askanna')['status'] == 'ACTIVE'


@pytest.mark.parametrize('fault', ['confirmation', 'other_app', 'tampered', 'expired'])
@pytest.mark.asyncio
async def test_confirmation_receipt_cannot_delete_wrong_app(client, superadmin_user, db_session, fault, monkeypatch):
    data = await preview(client, superadmin_user)
    confirmation = 'askanna'
    if fault == 'confirmation': confirmation = 'roomlyst'
    if fault == 'other_app': data = await preview(client, superadmin_user, 'roomlyst')
    if fault == 'tampered': data['preview_token'] += 'x'
    if fault == 'expired': monkeypatch.setattr(app_deletion.time, 'time', lambda: 99999999999)
    response = await client.request('DELETE', '/api/v1/apps/askanna', headers=headers(superadmin_user), json={'confirmation': confirmation, 'preview_token': data['preview_token']})
    assert response.status_code == 409
    assert db_session.get_app('askanna')['status'] == 'ACTIVE'
    assert not db_session.db.deletions_col.document('askanna').get().exists


@pytest.mark.asyncio
async def test_partial_delete_pauses_writes_and_resumes_without_auto_deletion(client, superadmin_user, db_session):
    for index in range(125):
        db_session.db.events_col('askanna', 'test').document(f'event-{index}').set({'app_id': 'askanna'})
    data = await preview(client, superadmin_user)
    first = await remove(client, superadmin_user, data)
    assert first.status_code == 202 and first.json()['status'] == 'deleting'
    assert len(db_session.db.events_col('askanna', 'test').get()) == 25
    assert db_session.get_app('askanna')['status'] == 'DELETING'
    assert (await client.patch('/api/v1/apps/askanna', headers=headers(superadmin_user), json={'status': 'ACTIVE'})).status_code == 409
    for operation in [
        lambda: db_session.create_api_key('new', 'askanna', 'test', 'new', 'synthetic', 'New'),
        lambda: db_session.grant_user_app_permission('new-user', 'askanna', 'AppAdmin'),
        lambda: db_session.touch_session('askanna', 'test', {'session_id': 'late'}),
        lambda: db_session.claim_and_ingest_event('askanna', 'test', 'late', {}, {'session_id': 'late'}),
    ]:
        with pytest.raises(ValueError): operation()
    final = await remove(client, superadmin_user, data)
    assert final.status_code == 200 and db_session.get_app('askanna') is None
    assert not db_session.db.events_col('askanna', 'test').get()


@pytest.mark.asyncio
async def test_cleanup_failure_reports_interruption_and_can_be_retried(client, superadmin_user, db_session, monkeypatch):
    seed_related(db_session, 'askanna')
    data = await preview(client, superadmin_user)
    original = MockDocumentReference.delete
    def unavailable(self):
        if '/askanna_live/' in self.path: raise RuntimeError('synthetic interrupted delete')
        original(self)
    monkeypatch.setattr(MockDocumentReference, 'delete', unavailable)
    response = await remove(client, superadmin_user, data)
    assert response.status_code == 503
    assert db_session.get_app('askanna')['status'] == 'DELETING'
    monkeypatch.setattr(MockDocumentReference, 'delete', original)
    assert (await remove(client, superadmin_user, data)).status_code == 200


@pytest.mark.asyncio
async def test_conflicting_ownership_stops_preview_without_any_writes(client, superadmin_user, db_session):
    db_session.db.events_col('askanna', 'live').document('foreign').set({'app_id': 'roomlyst'})
    before = copy.deepcopy(db_session.db.client._store)
    response = await client.get('/api/v1/apps/askanna/deletion-preview', headers=headers(superadmin_user))
    assert response.status_code == 409
    assert db_session.db.client._store == before


@pytest.mark.asyncio
async def test_delete_cookie_auth_enforces_csrf(client, superadmin_user, db_session):
    login = await client.post('/api/v1/auth/google', json={'id_token': f'mock_google_id_token:{superadmin_user.email}:delete-csrf'})
    data = await preview(client, superadmin_user)
    response = await client.request('DELETE', '/api/v1/apps/askanna', cookies=dict(login.cookies), json={'confirmation': 'askanna', 'preview_token': data['preview_token']})
    assert response.status_code == 403
    assert db_session.get_app('askanna')['status'] == 'ACTIVE'


@pytest.mark.asyncio
async def test_preview_is_bounded_and_reports_lower_bound_without_starting_job(client, superadmin_user, db_session):
    for index in range(2005):
        db_session.db.events_col('askanna', 'test').document(str(index)).set({'app_id': 'askanna'})
    result = await preview(client, superadmin_user)
    assert result['truncated'] is True and sum(result['counts'].values()) == 2000
    assert not db_session.db.deletions_col.document('askanna').get().exists
    assert len(db_session.db.events_col('askanna', 'test').get()) == 2005


def test_deletion_refuses_nonanalytics_namespace_before_writes(db_session, monkeypatch):
    monkeypatch.setattr(db_session.db, 'prefix', '')
    with pytest.raises(ValueError, match='namespace'):
        app_deletion.delete_step(db_session, 'askanna', 'askanna', 'invalid', 'synthetic')


def test_ingestion_transaction_rolls_back_and_respects_deletion_fence(db_session, monkeypatch):
    original = MockDocumentReference.set
    def unavailable(self, data, **kwargs):
        if '/events/' in self.path: raise RuntimeError('synthetic persistence failure')
        original(self, data, **kwargs)
    monkeypatch.setattr(MockDocumentReference, 'set', unavailable)
    with pytest.raises(RuntimeError):
        db_session.claim_and_ingest_event('askanna', 'test', 'rollback', {}, {'session_id': 'rollback'})
    assert not db_session.db.idempotency_col.document('askanna_test_rollback').get().exists
    assert not db_session.db.sessions_col('askanna', 'test').get()
