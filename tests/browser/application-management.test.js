const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const tick = () => new Promise(resolve => setImmediate(resolve));

function harness({ role = 'SuperAdmin', initialApps = [], deferKey = false, recent = [], deletionPartial = false, deletionError = false } = {}) {
  const elements = new Map(), calls = [], store = new Map(), docEvents = {}, windowEvents = {};
  let apps = initialApps.map(app => ({ ...app })), keys = [], pendingKey, deleteCalls = 0;
  function element(id = '') {
    const classes = new Set();
    return {
      id, children: [], handlers: {}, attributes: {}, value: id === 'date-range-filter' ? '7d' : '',
      textContent: '', innerHTML: '', disabled: false,
      classList: { add: x => classes.add(x), remove: x => classes.delete(x), contains: x => classes.has(x) },
      appendChild(child) { this.children.push(child); return child; },
      replaceChildren(...children) { this.children = children; this.textContent = ''; },
      addEventListener(event, fn) { this.handlers[event] = fn; },
      setAttribute(key, value) { this.attributes[key] = value; },
      reportValidity() { return true; }, reset() {}, focus() {},
    };
  }
  const get = id => { if (!elements.has(id)) elements.set(id, element(id)); return elements.get(id); };
  const response = (status, data) => ({ status, ok: status < 300, json: async () => data });
  const context = vm.createContext({
    document: { cookie: 'csrf_token=synthetic-csrf', visibilityState: 'visible', getElementById: get,
      createElement: () => element(), addEventListener: (event, fn) => { docEvents[event] = fn; } },
    window: { addEventListener: (event, fn) => { windowEvents[event] = fn; } },
    localStorage: { getItem: key => store.get(key) || null, setItem: (key, value) => store.set(key, value), removeItem: key => store.delete(key) },
    navigator: { clipboard: { writeText: async () => {} } },
    URLSearchParams, Date, confirm: () => true, alert: () => {},
    console: { error() {}, warn() {} }, setTimeout: () => 1, setInterval: () => 1, clearInterval() {},
    fetch: async (url, options = {}) => {
      calls.push({ url, options });
      const method = options.method || 'GET';
      if (url === '/api/v1/auth/config') return response(200, { google_client_id: null });
      if (url === '/api/v1/auth/me') return response(200, { email: 'synthetic@example.com', role });
      if (url === '/api/v1/auth/logout') return response(200, {});
      if (url.includes('/api/v1/analytics/recent')) return response(200, recent);
      if (url.endsWith('/deletion-preview')) return response(200, {
        app_id: 'askanna', name: 'AskAnna', status: apps[0].status, counts: { keys: 2, live_events: 3, test_events: 4 },
        catalog_documents: 1, truncated: false, preview_token: 'synthetic-preview',
        notice: 'Both LIVE and TEST data are deleted.', retained: 'Audit logs and retired-ID marker retained.',
      });
      if (method === 'DELETE' && url === '/api/v1/apps/askanna') {
        deleteCalls++;
        if (deletionError) return response(503, { detail: 'Cleanup interrupted; resume deletion.' });
        if (deletionPartial && deleteCalls === 1) {
          apps[0].status = 'DELETING';
          return response(202, { status: 'deleting', message: 'Cleanup is not complete. Resume deletion to continue.' });
        }
        apps = []; return response(200, { status: 'deleted' });
      }
      if (url === '/api/v1/apps') {
        if (method === 'POST') {
          const data = JSON.parse(options.body);
          if (apps.some(app => app.app_id === data.app_id)) return response(409, { detail: 'Application already exists' });
          const app = { ...data, status: 'ACTIVE', can_manage: true };
          apps.push(app); return response(201, app);
        }
        return response(200, apps);
      }
      if (url.includes('/keys')) {
        if (method === 'POST') {
          const data = JSON.parse(options.body);
          const key = { id: `key-${keys.length}`, ...data, prefix: `apk_${data.environment}_prefix`, status: 'ACTIVE', created_at: '2026-11-04' };
          keys.push(key);
          const result = response(201, { ...key, raw_key: `apk_${data.environment}_synthetic_one_time` });
          if (deferKey) return new Promise(resolve => { pendingKey = () => resolve(result); });
          return result;
        }
        if (method === 'DELETE') { keys[0].status = 'REVOKED'; return response(204, null); }
        const env = url.split('?env=')[1];
        return response(200, keys.filter(key => key.environment === env));
      }
      if (method === 'PATCH') {
        const app = apps.find(a => url.endsWith('/' + a.app_id));
        Object.assign(app, JSON.parse(options.body)); return response(200, app);
      }
      return response(503, {});
    },
  });
  for (const filename of ['applications.js', 'app.js']) {
    vm.runInContext(readFileSync(path.join(__dirname, '../../dashboard', filename), 'utf8'), context);
  }
  const click = (id) => get(id).handlers.click();
  const submit = (id) => get(id).handlers.submit({ preventDefault() {} });
  const rowButton = (row, label) => row.children.at(-1).children.find(b => b.textContent === label);
  return { get, calls, store, click, submit, rowButton, context, docEvents, windowEvents, releaseKey: () => pendingKey() };
}

const app = { app_id: 'askanna', name: 'AskAnna', status: 'ACTIVE', can_manage: true,
  live_origins: 'https://askanna.online', test_origins: 'https://test.askanna.online' };

test('empty dashboard registers AskAnna and refreshes the real selector without reload', async () => {
  const h = harness(); await tick();
  assert.equal(h.get('dashboard-container').classList.contains('hidden'), false);
  h.click('app-add'); h.click('app-preset');
  assert.equal(h.get('app-name').value, 'AskAnna');
  await h.submit('app-form');
  assert.equal(h.get('app-selector').value, 'askanna');
  assert(h.get('app-selector').innerHTML.includes('AskAnna'));
  const request = h.calls.find(c => c.url === '/api/v1/apps' && c.options.method === 'POST');
  assert.equal(request.options.headers['X-CSRF-Token'], 'synthetic-csrf');
  assert.equal(JSON.parse(request.options.body).live_origins, 'https://askanna.online');
  assert.equal(JSON.parse(request.options.body).test_origins, 'https://test.askanna.online');
});

test('edit keeps the identifier fixed, escapes selector names, and deactivation removes active selection', async () => {
  const h = harness({ initialApps: [app] }); await tick();
  let row = h.get('application-rows').children[0];
  h.rowButton(row, 'Edit').handlers.click();
  assert.equal(h.get('app-id').disabled, true);
  h.get('app-name').value = '<img src=x onerror=alert(1)>';
  await h.submit('app-form');
  assert(!h.get('app-selector').innerHTML.includes('<img'));
  assert(h.get('app-selector').innerHTML.includes('&lt;img'));
  row = h.get('application-rows').children[0];
  assert.equal(row.children[0].textContent, '<img src=x onerror=alert(1)> (askanna)');
  await h.rowButton(row, 'Deactivate').handlers.click();
  assert.equal(h.get('app-selector').value, '');
  assert.equal(h.get('application-empty').classList.contains('hidden'), false);
});

test('generated keys are transient, separated by environment, and cleared on dismissal and logout', async () => {
  const h = harness({ initialApps: [app] }); await tick();
  await h.rowButton(h.get('application-rows').children[0], 'Collection keys').handlers.click();
  h.get('key-name').value = 'LIVE website'; await h.submit('key-form');
  assert.equal(h.get('key-value').textContent, 'apk_live_synthetic_one_time');
  assert.equal(h.store.size, 0);
  assert.equal(h.get('key-rows').children[0].children[1].textContent, 'apk_live_prefix');
  await h.click('keys-test'); assert.equal(h.get('key-value').textContent, '');
  h.get('key-name').value = 'TEST website'; await h.submit('key-form');
  assert.equal(h.get('key-value').textContent, 'apk_test_synthetic_one_time');
  h.click('key-dismiss'); assert.equal(h.get('key-value').textContent, '');
  h.get('key-name').value = 'Another test'; await h.submit('key-form');
  await h.click('btn-logout'); assert.equal(h.get('key-value').textContent, '');
});

test('dismissal or logout while generation is in flight prevents a late key reveal', async () => {
  for (const action of ['key-dismiss', 'btn-logout']) {
    const h = harness({ initialApps: [app], deferKey: true }); await tick();
    await h.rowButton(h.get('application-rows').children[0], 'Collection keys').handlers.click();
    h.get('key-name').value = 'Pending';
    const request = h.submit('key-form'); await tick();
    await h.click(action); h.releaseKey(); await request;
    assert.equal(h.get('key-value').textContent, '');
  }
});

test('viewers see no mutation controls and raw key views clear when the page is hidden', async () => {
  const viewer = harness({ role: 'AppViewer', initialApps: [{ ...app, can_manage: false }] }); await tick();
  assert(viewer.get('app-add').classList.contains('hidden'));
  assert.equal(viewer.get('application-rows').children[0].children.at(-1).textContent, 'View only');
  const h = harness({ initialApps: [app] }); await tick();
  await h.rowButton(h.get('application-rows').children[0], 'Collection keys').handlers.click();
  h.get('key-name').value = 'Hidden'; await h.submit('key-form');
  h.context.document.visibilityState = 'hidden'; h.docEvents.visibilitychange();
  assert.equal(h.get('key-value').textContent, '');
});

test('Analytics and Applications navigation separates views and clears one-time keys', async () => {
  const h = harness({ initialApps: [app] }); await tick();
  assert(h.get('application-management').classList.contains('hidden'));
  assert(!h.get('analytics-view').classList.contains('hidden'));
  h.click('nav-applications');
  assert(h.get('analytics-view').classList.contains('hidden'));
  assert(!h.get('application-management').classList.contains('hidden'));
  assert.equal(h.get('app-selector').disabled, true);
  await h.rowButton(h.get('application-rows').children[0], 'Collection keys').handlers.click();
  h.get('key-name').value = 'Transient'; await h.submit('key-form');
  assert(h.get('key-value').textContent);
  h.click('nav-analytics');
  assert.equal(h.get('key-value').textContent, '');
  assert.equal(h.get('app-selector').disabled, false);
});

test('delete requires impact preview and exact typing; partial cleanup never auto-continues', async () => {
  const h = harness({ initialApps: [{ ...app, can_delete: true }], deletionPartial: true }); await tick();
  h.click('nav-applications');
  await h.rowButton(h.get('application-rows').children[0], 'Delete permanently').handlers.click();
  assert(h.get('app-delete-impact').textContent.includes('live_events'));
  assert(h.get('app-delete-retained').textContent.includes('Audit'));
  h.get('app-delete-confirmation').value = 'ASKANNA'; await h.submit('app-delete-form');
  assert.equal(h.calls.filter(call => call.options.method === 'DELETE').length, 0);
  h.get('app-delete-confirmation').value = 'askanna';
  h.get('app-delete-confirmation').handlers.input();
  assert.equal(h.get('app-delete-submit').disabled, false);
  await h.submit('app-delete-form');
  assert.equal(h.calls.filter(call => call.options.method === 'DELETE').length, 1);
  assert(h.get('app-delete-message').textContent.includes('not complete'));
  assert.equal(h.get('app-delete-submit').textContent, 'Continue cleanup');
  await h.submit('app-delete-form');
  assert.equal(h.get('app-selector').value, '');
  assert(h.get('app-message').textContent.includes('deleted permanently'));
});

test('delete is hidden from AppAdmin and interrupted cleanup does not report success', async () => {
  const admin = harness({ role: 'AppAdmin', initialApps: [{ ...app, can_delete: false }] }); await tick();
  assert.equal(admin.rowButton(admin.get('application-rows').children[0], 'Delete permanently'), undefined);
  const h = harness({ initialApps: [{ ...app, can_delete: true }], deletionError: true }); await tick();
  await h.rowButton(h.get('application-rows').children[0], 'Delete permanently').handlers.click();
  h.get('app-delete-confirmation').value = 'askanna'; await h.submit('app-delete-form');
  assert(h.get('app-delete-message').textContent.includes('interrupted'));
  assert(!h.get('app-message').textContent.includes('deleted permanently'));
  h.click('nav-analytics');
  assert.equal(h.get('app-delete-confirmation').value, '');
});

test('recent events show full UTC time, reported source and expandable technical details as text', async () => {
  const h = harness({ initialApps: [app], recent: [{
    timestamp: '2026-11-05T10:00:00+08:00', event_type: 'custom', event_name: 'example_action',
    page_path: '/action', source: 'flask_example', metadata: { source: 'flask_example', status_code: 201 },
    country_code: null, duration_ms: 25,
  }] }); await tick();
  const row = h.get('recent-table-body').children[0];
  assert.equal(row.children[0].textContent, '2026-11-05T02:00:00.000Z');
  assert.equal(row.children[4].textContent, 'flask_example');
  const details = row.children[5].children[0];
  assert.equal(details.children[0].textContent, 'View details');
  const payload = JSON.parse(details.children[1].textContent);
  assert.equal(payload.metadata.status_code, 201);
  assert.equal(payload.country, 'Unknown');
  assert.equal(row.innerHTML, '');
});

test('app classifications use explicit metadata rather than names or TEST credentials', async () => {
  const h = harness({ initialApps: [{ ...app, app_id: 'smoke-app-real' }, { ...app, app_id: 'declared-sample', classification: 'SAMPLE' }] });
  await tick();
  assert.equal(h.get('application-rows').children[0].children[0].children[0].textContent, 'Unclassified');
  assert.equal(h.get('application-rows').children[1].children[0].children[0].textContent, 'Sample / test (declared)');
});
