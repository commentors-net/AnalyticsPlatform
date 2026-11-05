"""Application management, one-time keys, authorization and browser environment boundaries."""
import uuid

import pytest

from api.app.core.rate_limit import rate_limiter

ASKANNA = {"name": "AskAnna", "live_origins": "https://askanna.online", "test_origins": "https://test.askanna.online"}


async def auth(client, email):
    response = await client.post('/api/v1/auth/google', json={'id_token': f'mock_google_id_token:{email}:management-subject'})
    assert response.status_code == 200
    return {'Authorization': f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_registration_update_and_duplicate_preserves_original(client, superadmin_user):
    headers = await auth(client, superadmin_user.email)
    payload = {"app_id": "new-managed-app", **ASKANNA}
    created = await client.post('/api/v1/apps', headers=headers, json=payload)
    assert created.status_code == 201
    assert created.json()['can_manage'] is True
    assert created.json()['live_origins'] == ASKANNA['live_origins']
    duplicate = await client.post('/api/v1/apps', headers=headers, json={**payload, 'name': 'Overwrite attempt'})
    assert duplicate.status_code == 409
    fetched = await client.get('/api/v1/apps/new-managed-app', headers=headers)
    assert fetched.json()['name'] == 'AskAnna'
    updated = await client.patch('/api/v1/apps/new-managed-app', headers=headers, json={'name': 'Renamed'})
    assert updated.status_code == 200
    assert updated.json()['test_origins'] == ASKANNA['test_origins']
    assert updated.json()['created_at'] == created.json()['created_at']


@pytest.mark.asyncio
async def test_askanna_environment_keys_one_time_revocation_and_deactivation(client, superadmin_user, db_session):
    rate_limiter.reset()
    headers = await auth(client, superadmin_user.email)
    updated = await client.patch('/api/v1/apps/askanna', headers=headers, json=ASKANNA)
    assert updated.status_code == 200
    assert updated.json()['name'] == 'AskAnna'
    keys = {}
    for environment in ('live', 'test'):
        result = await client.post('/api/v1/apps/askanna/keys', headers=headers, json={'environment': environment, 'name': environment.upper()})
        assert result.status_code == 201
        assert result.headers['cache-control'] == 'no-store'
        keys[environment] = result.json()
        assert keys[environment]['raw_key'].startswith(f'apk_{environment}_')
        listing = await client.get(f'/api/v1/apps/askanna/keys?env={environment}', headers=headers)
        assert len(listing.json()) == 1
        assert listing.json()[0]['environment'] == environment
        assert 'raw_key' not in listing.json()[0] and 'key_hash' not in listing.json()[0]
    assert all('raw_key' not in record for record in db_session.list_api_keys('askanna'))

    async def send(environment, origin, batch=False):
        event = {'event_id': str(uuid.uuid4()), 'event_name': 'management_probe', 'page_path': '/'}
        return await client.post('/v1/events/batch' if batch else '/v1/events',
                                 headers={'X-Write-Key': keys[environment]['raw_key'], 'Origin': origin},
                                 json={'batch': [event]} if batch else event)

    for batch in (False, True):
        assert (await send('live', ASKANNA['live_origins'], batch)).status_code in (201, 202)
        assert (await send('test', ASKANNA['test_origins'], batch)).status_code in (201, 202)
        assert (await send('live', ASKANNA['test_origins'], batch)).status_code == 403
        assert (await send('test', ASKANNA['live_origins'], batch)).status_code == 403
    assert (await send('live', 'http://askanna.online')).status_code == 403
    assert (await send('live', 'https://askanna.online:8443')).status_code == 403
    assert (await send('live', 'https://evilaskanna.online')).status_code == 403

    revoked = await client.delete(f"/api/v1/apps/askanna/keys/{keys['test']['id']}", headers=headers)
    assert revoked.status_code == 204
    assert (await send('test', ASKANNA['test_origins'])).status_code == 401
    assert (await send('live', ASKANNA['live_origins'])).status_code == 201
    inactive = await client.patch('/api/v1/apps/askanna', headers=headers, json={'status': 'SUSPENDED'})
    assert inactive.status_code == 200
    assert (await send('live', ASKANNA['live_origins'])).status_code == 401
    assert (await client.post('/api/v1/apps/askanna/keys', headers=headers, json={'environment': 'live', 'name': 'Inactive'})).status_code == 409


@pytest.mark.asyncio
async def test_app_permissions_are_enforced_by_server(client, db_session):
    user = db_session.create_user(email='app-viewer@example.com', role='AppViewer')
    headers = await auth(client, user['email'])
    assert (await client.get('/api/v1/apps', headers=headers)).json() == []
    assert (await client.post('/api/v1/apps', headers=headers, json={'app_id': 'forbidden', **ASKANNA})).status_code == 403
    assert (await client.patch('/api/v1/apps/askanna', headers=headers, json={'name': 'Forbidden'})).status_code == 403
    db_session.grant_user_app_permission(user['id'], 'askanna', 'AppViewer')
    assert (await client.get('/api/v1/apps', headers=headers)).json()[0]['can_manage'] is False
    assert (await client.patch('/api/v1/apps/askanna', headers=headers, json={'status': 'SUSPENDED'})).status_code == 403
    assert (await client.post('/api/v1/apps/askanna/keys', headers=headers, json={'environment': 'test', 'name': 'Forbidden'})).status_code == 403
    db_session.grant_user_app_permission(user['id'], 'askanna', 'AppAdmin')
    assert (await client.get('/api/v1/apps', headers=headers)).json()[0]['can_manage'] is True
    assert (await client.patch('/api/v1/apps/askanna', headers=headers, json=ASKANNA)).status_code == 200
    assert (await client.patch('/api/v1/apps/roomlyst', headers=headers, json={'status': 'SUSPENDED'})).status_code == 403
    assert (await client.post('/api/v1/apps/askanna/keys', headers=headers, json={'environment': 'test', 'name': 'Allowed'})).status_code == 201
    assert (await client.post('/api/v1/apps', headers=headers, json={'app_id': 'still-forbidden', **ASKANNA})).status_code == 403


@pytest.mark.parametrize('changes', [
    {'name': '   '}, {'name': None}, {}, {'app_id': 'rename-forbidden'},
    {'live_origins': '*'}, {'test_origins': 'https://example.com/path'},
    {'live_origins': 'https://person:password@example.com'},
    {'live_origins': 'https://example.com?token=synthetic'}, {'test_origins': 'http://example.com'},
])
@pytest.mark.asyncio
async def test_management_rejects_unsafe_or_invalid_updates(client, superadmin_user, changes):
    headers = await auth(client, superadmin_user.email)
    assert (await client.patch('/api/v1/apps/askanna', headers=headers, json=changes)).status_code == 422


@pytest.mark.asyncio
async def test_new_app_cookie_mutations_require_csrf(client, superadmin_user):
    login = await client.post('/api/v1/auth/google', json={'id_token': f'mock_google_id_token:{superadmin_user.email}:cookie-management'})
    cookies = dict(login.cookies)
    response = await client.patch('/api/v1/apps/askanna', cookies=cookies, json={'status': 'SUSPENDED'})
    assert response.status_code == 403
    response = await client.patch('/api/v1/apps/askanna', cookies=cookies, headers={'X-CSRF-Token': login.json()['csrf_token']}, json=ASKANNA)
    assert response.status_code == 200


@pytest.mark.parametrize('exists', [False, True])
def test_askanna_registration_helper_creates_or_updates_only_authorized_app(exists):
    import json
    import httpx
    from scripts.register_askanna import register

    writes = []

    def transport(request):
        if request.method == 'GET':
            assert request.url.path == '/api/v1/apps/askanna'
            return httpx.Response(200, json={'app_id': 'askanna', 'name': 'Legacy'}) if exists else httpx.Response(404)
        writes.append(request)
        body = json.loads(request.content)
        assert request.url.path == ('/api/v1/apps/askanna' if exists else '/api/v1/apps')
        assert request.method == ('PATCH' if exists else 'POST')
        assert all(body[key] == value for key, value in ASKANNA.items())
        return httpx.Response(200 if exists else 201, json={'app_id': 'askanna', 'status': 'ACTIVE', **body})

    with httpx.Client(base_url='https://local.test', transport=httpx.MockTransport(transport)) as client:
        result = register(client, {'Authorization': 'Bearer synthetic'})
    assert len(writes) == 1
    assert result['app_id'] == 'askanna'
