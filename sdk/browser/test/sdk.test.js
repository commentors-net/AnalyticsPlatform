/**
 * Unit tests for the Browser Analytics SDK.
 * Runs on Node 22 native test runner.
 */

const test = require('node:test');
const assert = require('node:assert');

// Mock browser globals for testing
class MockStorage {
  constructor() {
    this.store = {};
  }
  getItem(key) {
    return this.store[key] || null;
  }
  setItem(key, value) {
    this.store[key] = String(value);
  }
  removeItem(key) {
    delete this.store[key];
  }
  clear() {
    this.store = {};
  }
}

global.localStorage = new MockStorage();
global.sessionStorage = new MockStorage();
global.window = {
  localStorage: global.localStorage,
  sessionStorage: global.sessionStorage,
  location: { pathname: '/dashboard', search: '?view=metrics&token=secret_abc123', hash: '#/overview' },
  addEventListener: () => {},
};
global.document = {
  referrer: 'https://partner.company.com/referral?campaign=summer',
  readyState: 'complete',
  addEventListener: () => {},
};

// Import compiled CJS bundle
const {
  StorageManager,
  SessionManager,
  TransportManager,
  sanitizeUrlPath,
  sanitizeReferrer,
  sanitizeMetadata,
  AnalyticsTracker,
} = require('../dist/index.js');

test('StorageManager - Three-Tier Consent Enforcement', async (t) => {
  localStorage.clear();
  sessionStorage.clear();

  await t.test('NO_STORAGE mode stores nothing and returns null visitor_id', () => {
    const sm = new StorageManager('NO_STORAGE');
    assert.strictEqual(sm.getConsent(), 'NO_STORAGE');
    assert.strictEqual(sm.getVisitorId(), null);
    assert.strictEqual(sm.isReturningVisitor(), false);
    sm.setSessionData('test-session');
    assert.strictEqual(sm.getSessionData(), null);
    assert.strictEqual(Object.keys(localStorage.store).length, 0);
    assert.strictEqual(Object.keys(sessionStorage.store).length, 0);
  });

  await t.test('ANONYMOUS mode uses sessionStorage only, no localStorage visitor_id', () => {
    const sm = new StorageManager('ANONYMOUS');
    assert.strictEqual(sm.getConsent(), 'ANONYMOUS');
    assert.strictEqual(sm.getVisitorId(), null);
    assert.strictEqual(sm.isReturningVisitor(), false);
    sm.setSessionData('session-123');
    assert.strictEqual(sm.getSessionData(), 'session-123');
    assert.strictEqual(localStorage.getItem('ap_vid'), null);
  });

  await t.test('ANALYTICS_ALLOWED mode persists visitor_id in localStorage', () => {
    const sm = new StorageManager('ANALYTICS_ALLOWED');
    assert.strictEqual(sm.getConsent(), 'ANALYTICS_ALLOWED');
    const vid1 = sm.getVisitorId();
    assert.ok(vid1 && vid1.length > 10);
    const vid2 = sm.getVisitorId();
    assert.strictEqual(vid1, vid2, 'visitor_id must be persistent');
  });

  await t.test('Stale localStorage cannot upgrade an explicit ANONYMOUS or NO_STORAGE consent (M2-05)', () => {
    localStorage.setItem('ap_consent', 'ANALYTICS_ALLOWED');
    localStorage.setItem('ap_vid', 'stale-visitor-id-12345');

    const sm = new StorageManager('ANONYMOUS');
    assert.strictEqual(sm.getConsent(), 'ANONYMOUS');
    assert.strictEqual(sm.getVisitorId(), null);
    assert.strictEqual(localStorage.getItem('ap_vid'), null, 'Stale visitor ID must be purged');

    localStorage.setItem('ap_consent', 'ANALYTICS_ALLOWED');
    localStorage.setItem('ap_vid', 'stale-visitor-id-67890');
    const smNoStorage = new StorageManager('NO_STORAGE');
    assert.strictEqual(smNoStorage.getConsent(), 'NO_STORAGE');
    assert.strictEqual(smNoStorage.getVisitorId(), null);
    assert.strictEqual(localStorage.getItem('ap_vid'), null, 'Stale visitor ID must be purged in NO_STORAGE');
  });

  await t.test('Downgrading to NO_STORAGE purges all stored identifiers (M2-06)', () => {
    localStorage.clear();
    sessionStorage.clear();
    const sm = new StorageManager('ANALYTICS_ALLOWED');
    sm.getVisitorId();
    sm.setSessionData('ses-active');
    assert.ok(localStorage.getItem('ap_vid'));
    assert.ok(sessionStorage.getItem('ap_ses'));

    sm.setConsent('NO_STORAGE');
    assert.strictEqual(sm.getConsent(), 'NO_STORAGE');
    assert.strictEqual(localStorage.getItem('ap_vid'), null);
    assert.strictEqual(sessionStorage.getItem('ap_ses'), null);
  });

  await t.test('isReturningVisitor requires firstSeen to be > 30 minutes ago and within 365 days (M2-17)', () => {
    localStorage.clear();
    const sm = new StorageManager('ANALYTICS_ALLOWED');
    sm.getVisitorId(); // sets first_seen to now
    // Immediate second call should NOT be returning
    assert.strictEqual(sm.isReturningVisitor(), false);

    // Simulate 31 minutes ago
    const thirtyOneMinsAgo = Date.now() - (31 * 60 * 1000);
    localStorage.setItem('ap_fs', String(thirtyOneMinsAgo));
    assert.strictEqual(sm.isReturningVisitor(), true);

    // Simulate 366 days ago (expired)
    const expiredTimestamp = Date.now() - (366 * 24 * 60 * 60 * 1000);
    localStorage.setItem('ap_fs', String(expiredTimestamp));
    assert.strictEqual(sm.isReturningVisitor(), false, 'Expired first_seen must reset returning status');
  });
});

test('Sanitizer - URL and Metadata Scrubbing', async (t) => {
  await t.test('redacts sensitive query parameters in URL path and preserves hash (M2-17)', () => {
    const dirtyUrl = '/checkout/pay?token=xyz123&auth=bearer99&code=oauth_code&amount=50#/step2';
    const cleanUrl = sanitizeUrlPath(dirtyUrl);
    assert.ok(cleanUrl.includes('token=%5BREDACTED%5D') || cleanUrl.includes('token=[REDACTED]'));
    assert.ok(cleanUrl.includes('auth=%5BREDACTED%5D') || cleanUrl.includes('auth=[REDACTED]'));
    assert.ok(cleanUrl.includes('code=%5BREDACTED%5D') || cleanUrl.includes('code=[REDACTED]'));
    assert.ok(cleanUrl.includes('amount=50'));
    assert.ok(cleanUrl.includes('#/step2'));
    assert.ok(!cleanUrl.includes('xyz123'));
    assert.ok(!cleanUrl.includes('bearer99'));
  });

  await t.test('extracts clean referrer hostname including naked domains (M2-17)', () => {
    assert.strictEqual(sanitizeReferrer('https://subdomain.google.com/search?q=cars&hl=en'), 'subdomain.google.com');
    assert.strictEqual(sanitizeReferrer('http://user:pass@example.com:8080/path'), 'example.com');
    assert.strictEqual(sanitizeReferrer('//cdn.example.org/resource'), 'cdn.example.org');
    assert.strictEqual(sanitizeReferrer('example.net'), 'example.net');
    assert.strictEqual(sanitizeReferrer(null), null);
  });

  await t.test('filters recursive prohibited metadata fields (PII, VIN, chat, nested objects) (M2-07)', () => {
    const dirtyMeta = {
      vin: '1HGCR2F83HA000000',
      chat_message: 'Please update my credit card info',
      password: 'mypassword',
      ssn: '123-45-6789',
      source: 'web_portal',
      feature_flag: true,
      score: 42,
      user_profile: {
        email: 'user@example.com',
        phone: '+15551234567',
        preferences: {
          theme: 'dark',
          secret_key: 'nested-leak',
          location: {
            latitude: 37.77,
            longitude: -122.41,
          },
        },
      },
    };
    const cleanMeta = sanitizeMetadata(dirtyMeta);
    assert.strictEqual(cleanMeta.vin, undefined);
    assert.strictEqual(cleanMeta.chat_message, undefined);
    assert.strictEqual(cleanMeta.password, undefined);
    assert.strictEqual(cleanMeta.ssn, undefined);
    assert.strictEqual(cleanMeta.source, 'web_portal');
    assert.strictEqual(cleanMeta.feature_flag, true);
    assert.strictEqual(cleanMeta.score, 42);
    assert.strictEqual(cleanMeta.user_profile.email, undefined);
    assert.strictEqual(cleanMeta.user_profile.phone, undefined);
    assert.strictEqual(cleanMeta.user_profile.preferences.theme, 'dark');
    assert.strictEqual(cleanMeta.user_profile.preferences.secret_key, undefined);
    assert.strictEqual(cleanMeta.user_profile.preferences.location.latitude, undefined);
    assert.strictEqual(cleanMeta.user_profile.preferences.location.longitude, undefined);
  });
});

test('SessionManager - Lifecycle and Timeout', async (t) => {
  localStorage.clear();
  sessionStorage.clear();
  const sm = new StorageManager('ANONYMOUS');
  const sess = new SessionManager(sm);

  const sid = sess.getSessionId();
  assert.ok(sid && sid.startsWith('ses_'));

  sess.recordPageview('/home');
  sess.recordPageview('/pricing');
  assert.strictEqual(sess.getSessionId(), sid, 'Session ID must remain stable across pageviews');

  await t.test('Idle expiration renews session ID after 30 minutes (M2-17)', () => {
    // Manually backdate the stored session's lastActivity by 31 minutes
    const raw = sessionStorage.getItem('ap_ses');
    assert.ok(raw);
    const parsed = JSON.parse(raw);
    parsed.lastActivity = Date.now() - (31 * 60 * 1000);
    sessionStorage.setItem('ap_ses', JSON.stringify(parsed));

    const sess2 = new SessionManager(sm);
    const newSid = sess2.getSessionId();
    assert.notStrictEqual(newSid, sid, 'New session must be initialized after idle expiration');
  });
});

test('TransportManager - Queueing and Beacon Safety (M2-08, M2-09)', async (t) => {
  const config = {
    endpoint: 'http://localhost:5433',
    writeKey: 'apk_live_mock_key_123',
    consent: 'ANONYMOUS',
    batchSize: 50,
    flushIntervalMs: 2000,
  };

  const transport = new TransportManager(config);

  const sampleEvent = {
    event_id: '00000000-0000-4000-8000-000000000001',
    event_type: 'custom',
    event_name: 'test_event',
    visitor_id: null,
    session_id: 'ses_test',
    page_path: '/home',
    referrer: null,
    duration_ms: null,
    metadata: {},
    timestamp: new Date().toISOString(),
  };

  transport.enqueue(sampleEvent);
  assert.strictEqual(transport['queue'].length, 1);

  // Test queue purge on withdrawal (M2-06)
  transport.purgeQueue();
  assert.strictEqual(transport['queue'].length, 0, 'Queue must be empty after purge');
});

test('AnalyticsTracker - Fail-Open and Consent Withdrawal (M2-06, M2-17)', async (t) => {
  localStorage.clear();
  sessionStorage.clear();

  const tracker = new AnalyticsTracker({
    endpoint: 'http://localhost:5433',
    writeKey: 'apk_live_mock_key_123',
    consent: 'ANALYTICS_ALLOWED',
    autoPageview: false,
    autoSpa: false,
  });

  // Track initial pageview
  tracker.trackPageview('/test#/overview');
  assert.strictEqual(tracker.getConsent(), 'ANALYTICS_ALLOWED');

  // Withdraw consent to NO_STORAGE
  tracker.setConsent('NO_STORAGE');
  assert.strictEqual(tracker.getConsent(), 'NO_STORAGE');
  assert.strictEqual(localStorage.getItem('ap_vid'), null);
  assert.strictEqual(sessionStorage.getItem('ap_ses'), null);

  // Calling tracking methods in NO_STORAGE mode must never throw
  assert.doesNotThrow(() => {
    tracker.trackPageview('/test2');
    tracker.trackEvent('button_click', 'click', { button_id: 'submit' }, 120);
  });

  // Fresh NO_STORAGE initialization makes zero setItem calls (M2-05)
  let setItemCalls = 0;
  const origLocalSet = localStorage.setItem;
  const origSessionSet = sessionStorage.setItem;
  localStorage.setItem = () => { setItemCalls++; };
  sessionStorage.setItem = () => { setItemCalls++; };

  try {
    new StorageManager('NO_STORAGE');
    assert.strictEqual(setItemCalls, 0, 'Must not call setItem in NO_STORAGE');
  } finally {
    localStorage.setItem = origLocalSet;
    sessionStorage.setItem = origSessionSet;
  }

  // Frozen isReturning status per session (M2-17)
  localStorage.clear();
  sessionStorage.clear();
  const smTest = new StorageManager('ANALYTICS_ALLOWED');
  const smSession = new SessionManager(smTest);

  const firstStatus = smSession.isReturning();
  assert.strictEqual(firstStatus, false);
  // Simulate firstSeen being set earlier during the session
  localStorage.setItem('ap_fs', (Date.now() - 40 * 60 * 1000).toString());
  // Calling isReturning on the same session manager must stay false
  assert.strictEqual(smSession.isReturning(), false, 'Session returning status must be frozen once initialized');
});
