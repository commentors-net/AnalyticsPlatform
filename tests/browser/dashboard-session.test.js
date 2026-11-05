const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = readFileSync(path.join(__dirname, '../../dashboard/app.js'), 'utf8');
const settle = () => new Promise(resolve => setImmediate(resolve));

function dashboard({ logoutStatus = 200, logoutError = false, cookieOnly = false, unauthorized = false } = {}) {
  const store = new Map(cookieOnly ? [] : [['ap_admin_token', 'synthetic-token'], ['ap_csrf_token', 'stale-csrf']]);
  const elements = new Map();
  const requests = [];
  const alerts = [];
  const getElement = id => {
    if (!elements.has(id)) {
      const classes = new Set(id === 'dashboard-container' ? ['hidden'] : []);
      elements.set(id, {
        value: '7d', textContent: '', innerHTML: '', handlers: {},
        classList: { add: x => classes.add(x), remove: x => classes.delete(x), contains: x => classes.has(x) },
        addEventListener(name, handler) { this.handlers[name] = handler; },
      });
    }
    return elements.get(id);
  };
  const response = (status, data = {}) => ({ status, ok: status >= 200 && status < 300, json: async () => data });
  vm.runInNewContext(source, {
    document: { cookie: 'csrf_token=current-csrf', getElementById: getElement },
    window: {}, Date, URLSearchParams, console: { error() {}, warn() {} },
    setTimeout: () => 1, setInterval: () => 1, clearInterval: () => {},
    alert: message => alerts.push(message),
    localStorage: { getItem: key => store.get(key) || null, setItem: (key, value) => store.set(key, value), removeItem: key => store.delete(key) },
    fetch: async (url, options = {}) => {
      requests.push({ url, options });
      if (url === '/api/v1/auth/config') return response(200, { google_client_id: null });
      if (url === '/api/v1/auth/me') return response(200, { email: 'synthetic@example.com', role: 'SuperAdmin' });
      if (url === '/api/v1/apps') return response(unauthorized ? 401 : 200, [{ app_id: 'synthetic-app', name: 'Synthetic' }]);
      if (url === '/api/v1/auth/logout') {
        if (logoutError) throw new Error('synthetic network failure');
        return response(logoutStatus);
      }
      return response(503); // Data rendering is outside this session test.
    },
  });
  return { store, requests, alerts, getElement };
}

test('cookie-only restoration shows the authenticated user and sends fresh CSRF on logout', async () => {
  const d = dashboard({ cookieOnly: true });
  await settle();
  assert.equal(d.getElement('user-display').textContent, 'synthetic@example.com');
  assert.equal(d.getElement('dashboard-container').classList.contains('hidden'), false);
  await d.getElement('btn-logout').handlers.click();
  const request = d.requests.find(x => x.url === '/api/v1/auth/logout');
  assert.equal(request.options.headers['X-CSRF-Token'], 'current-csrf');
  assert.equal(request.options.headers.Authorization, undefined);
  assert.equal(d.getElement('dashboard-container').classList.contains('hidden'), true);
});

for (const options of [{ logoutStatus: 503 }, { logoutStatus: 403 }, { logoutError: true }]) {
  test(`failed logout retains session for retry: ${JSON.stringify(options)}`, async () => {
    const d = dashboard(options);
    await settle();
    await d.getElement('btn-logout').handlers.click();
    assert.equal(d.store.get('ap_admin_token'), 'synthetic-token');
    assert.equal(d.getElement('dashboard-container').classList.contains('hidden'), false);
    assert(d.alerts.some(x => x.includes('Please retry')));
  });
}

test('confirmed Bearer logout clears saved state and uses current cookie CSRF', async () => {
  const d = dashboard();
  await settle();
  await d.getElement('btn-logout').handlers.click();
  const request = d.requests.find(x => x.url === '/api/v1/auth/logout');
  assert.equal(request.options.headers.Authorization, 'Bearer synthetic-token');
  assert.equal(request.options.headers['X-CSRF-Token'], 'current-csrf');
  assert.equal(d.store.has('ap_admin_token'), false);
  assert.equal(d.store.has('ap_csrf_token'), false);
});

test('an already invalid session clears locally without recursively calling logout', async () => {
  const d = dashboard({ unauthorized: true });
  await settle();
  assert.equal(d.store.has('ap_admin_token'), false);
  assert.equal(d.requests.some(x => x.url === '/api/v1/auth/logout'), false);
});
