import copy
import uuid
from datetime import datetime, timezone

import pytest

from api.app.core.security import create_access_token
from api.app.services.geoip import resolve_coarse_geoip


@pytest.mark.asyncio
async def test_recent_details_project_safe_fields_and_preserve_environment_scope(client, superadmin_user, db_session):
    event_id = str(uuid.uuid4())
    record = {
        'event_id': event_id, 'event_name': 'example_action', 'event_type': 'custom',
        'timestamp': datetime.now(timezone.utc).isoformat(), 'page_path': '/users/private-person?token=private-value',
        'visitor_id': 'private-visitor', 'session_id': 'private-session', 'ip_masked': '127.0.0.0',
        'referrer_domain': 'private-referrer', 'country_code': 'LO', 'city_name': 'Localhost',
        'device_family': 'desktop', 'browser_family': 'Chrome', 'os_family': 'Linux', 'duration_ms': 25,
        'metadata': {'source': 'flask_example', 'status_code': 201, 'method': 'POST', 'is_bot': False,
                     'email': 'private@example.invalid', 'token': 'private-token', 'nested': {'message': 'private-text'}, 'unknown': 'private-unknown'},
    }
    db_session.db.events_col('askanna', 'live').document(event_id).set(record)
    db_session.db.events_col('askanna', 'test').document('test-only').set({**record, 'event_name': 'test_only'})
    before = copy.deepcopy(db_session.db.client._store)
    auth = {'Authorization': f"Bearer {create_access_token({'sub': str(superadmin_user.id)})}"}
    response = await client.get('/api/v1/analytics/recent?app_id=askanna&environment=live', headers=auth)
    assert response.status_code == 200
    item = response.json()[0]
    assert len(response.json()) == 1 and item['event_name'] == 'example_action'
    assert item['page_path'] == '/[hidden]/[hidden]'
    assert item['source'] == 'flask_example'
    assert item['metadata'] == {'source': 'flask_example', 'status_code': 201, 'method': 'POST', 'is_bot': False}
    assert 'private-' not in response.text and 'private@' not in response.text
    assert item['country_code'] is None and item['referrer_domain'] is None
    assert 'visitor_id' not in item and 'session_id' not in item and 'ip_masked' not in item
    geo = await client.get('/api/v1/analytics/geo?app_id=askanna&environment=live', headers=auth)
    assert geo.json()[0]['country_code'] == 'Unknown' and geo.json()[0]['city_name'] is None
    assert db_session.db.client._store == before  # Display does not rewrite legacy records.


@pytest.mark.asyncio
async def test_malformed_or_sensitive_legacy_details_do_not_leak_or_crash(client, superadmin_user, db_session):
    db_session.db.events_col('askanna', 'test').document('legacy').set({
        'event_id': 'apk_live_sensitive', 'timestamp': 'not-an-iso-date', 'event_name': 'apk_live_sensitive',
        'event_type': '<script>', 'page_path': '/pricing?email=private@example.invalid',
        'metadata': {'source': {'token': 'sensitive'}, 'status_code': float('inf'), 'is_bot': 'not-a-boolean'},
        'device_family': 'apk_live_sensitive', 'duration_ms': 'sensitive',
    })
    auth = {'Authorization': f"Bearer {create_access_token({'sub': str(superadmin_user.id)})}"}
    response = await client.get('/api/v1/analytics/recent?app_id=askanna&environment=test', headers=auth)
    assert response.status_code == 200
    item = response.json()[0]
    assert item['event_name'] == 'Hidden' and item['page_path'] == '/pricing'
    assert item['event_id'] == '' and item['timestamp'] == ''
    assert item['metadata'] == {} and item['source'] == 'Not reported'
    assert 'sensitive' not in response.text and '<script>' not in response.text


@pytest.mark.parametrize('address', [None, '127.0.0.1', '::1', '10.0.0.1', '192.168.1.1', '8.8.8.8', 'not-an-ip'])
def test_geography_without_lookup_is_unknown(address):
    assert resolve_coarse_geoip(address) == (None, None, None)


@pytest.mark.asyncio
async def test_classification_is_explicit_and_not_inferred_from_test_names(client, superadmin_user, db_session):
    db_session.create_app('smoke-app-real-name', 'Sample-looking name')
    auth = {'Authorization': f"Bearer {create_access_token({'sub': str(superadmin_user.id)})}"}
    result = await client.get('/api/v1/apps/smoke-app-real-name', headers=auth)
    assert result.json()['classification'] == 'UNCLASSIFIED'
    tagged = await client.patch('/api/v1/apps/smoke-app-real-name', headers=auth, json={'classification': 'REAL'})
    assert tagged.status_code == 200 and tagged.json()['classification'] == 'REAL'
    assert (await client.patch('/api/v1/apps/smoke-app-real-name', headers=auth, json={'classification': 'GUESSED'})).status_code == 422


@pytest.mark.asyncio
async def test_event_details_require_app_access(client, db_session):
    user = db_session.create_user(email='details-viewer@example.com', role='AppViewer')
    auth = {'Authorization': f"Bearer {create_access_token({'sub': user['id']})}"}
    assert (await client.get('/api/v1/analytics/recent?app_id=askanna&environment=live', headers=auth)).status_code == 403
    db_session.grant_user_app_permission(user['id'], 'askanna', 'AppViewer')
    assert (await client.get('/api/v1/analytics/recent?app_id=askanna&environment=test', headers=auth)).status_code == 200
    assert (await client.get('/api/v1/analytics/recent?app_id=roomlyst&environment=test', headers=auth)).status_code == 403
