/**
 * Analytics Platform Interactive Dashboard Application (Milestone M3).
 * Zero-dependency, client-side SPA communicating with /api/v1 endpoints.
 */

(function () {
  'use strict';

  function csrfCookie() {
    const entry = document.cookie.split(';').find((part) => part.trim().startsWith('csrf_token='));
    return entry ? decodeURIComponent(entry.trim().slice('csrf_token='.length)) : null;
  }

  // --- State ---
  let state = {
    token: localStorage.getItem('ap_admin_token') || null,
    csrfToken: csrfCookie() || localStorage.getItem('ap_csrf_token') || null,
    user: null,
    googleClientId: null,
    apps: [],
    selectedApp: null,
    selectedEnv: 'live',
    selectedRange: '7d',
    refreshTimer: null,
    section: 'analytics',
    analyticsRequest: 0,
  };

  const applicationManager = window.ApplicationManager ? new window.ApplicationManager({
    apiRequest,
    onChanged: async (preferredId) => { await refreshApplications(preferredId); await fetchDashboardData(); },
  }) : null;

  // --- DOM Elements ---
  const el = {
    loginContainer: document.getElementById('login-container'),
    dashboardContainer: document.getElementById('dashboard-container'),
    googleBtnTarget: document.getElementById('google-btn-target'),
    manualIdToken: document.getElementById('manual-id-token'),
    btnManualToken: document.getElementById('btn-manual-token'),
    loginError: document.getElementById('login-error'),
    userDisplay: document.getElementById('user-display'),
    btnLogout: document.getElementById('btn-logout'),
    appSelector: document.getElementById('app-selector'),
    envLive: document.getElementById('env-live'),
    envTest: document.getElementById('env-test'),
    testBanner: document.getElementById('test-banner'),
    dateRangeFilter: document.getElementById('date-range-filter'),
    btnExportCsv: document.getElementById('btn-export-csv'),
    // KPI elements
    kpiPageviews: document.getElementById('kpi-pageviews'),
    kpiPageviewsDelta: document.getElementById('kpi-pageviews-delta'),
    kpiVisitors: document.getElementById('kpi-visitors'),
    kpiVisitorsDelta: document.getElementById('kpi-visitors-delta'),
    kpiSessions: document.getElementById('kpi-sessions'),
    kpiSessionsDelta: document.getElementById('kpi-sessions-delta'),
    kpiBounce: document.getElementById('kpi-bounce'),
    kpiBounceDelta: document.getElementById('kpi-bounce-delta'),
    kpiDuration: document.getElementById('kpi-duration'),
    kpiDurationDelta: document.getElementById('kpi-duration-delta'),
    // Chart
    trendSvg: document.getElementById('trend-svg'),
    chartRangeLabel: document.getElementById('chart-range-label'),
    // Tables
    pagesBody: document.getElementById('pages-table-body'),
    referrersBody: document.getElementById('referrers-table-body'),
    geoBody: document.getElementById('geo-table-body'),
    recentBody: document.getElementById('recent-table-body'),
    deviceList: document.getElementById('device-list'),
    browserList: document.getElementById('browser-list'),
  };

  // --- API Client ---
  async function apiRequest(endpoint, options = {}) {
    const headers = options.headers || {};
    if (state.token) {
      headers['Authorization'] = `Bearer ${state.token}`;
    }
    // Include CSRF token for state-changing requests (Requirement 6)
    if (state.csrfToken && ['POST', 'PUT', 'DELETE', 'PATCH'].includes((options.method || 'GET').toUpperCase())) {
      headers['X-CSRF-Token'] = state.csrfToken;
    }
    const res = await fetch(endpoint, {
      ...options,
      headers,
      credentials: 'same-origin', // Send HttpOnly session cookies
    });
    if (res.status === 401) {
      clearLocalSession();
      throw new Error('Unauthorized');
    }
    return res;
  }

  // --- Google Authentication ---
  async function authenticateWithGoogleIdToken(idToken) {
    el.loginError.classList.add('hidden');
    try {
      const res = await fetch('/api/v1/auth/google', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ id_token: idToken }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Google authentication failed');
      }

      const data = await res.json();
      state.token = data.access_token;
      state.csrfToken = data.csrf_token;
      state.user = data.user;
      localStorage.setItem('ap_admin_token', state.token);
      if (state.csrfToken) {
        localStorage.setItem('ap_csrf_token', state.csrfToken);
      }
      await initDashboard();
    } catch (err) {
      el.loginError.textContent = err.message;
      el.loginError.classList.remove('hidden');
    }
  }

  // Manual Token / Testing Mode handler
  if (el.btnManualToken) {
    el.btnManualToken.addEventListener('click', () => {
      const token = el.manualIdToken.value.trim();
      if (!token) {
        el.loginError.textContent = 'Please paste a valid Google ID token';
        el.loginError.classList.remove('hidden');
        return;
      }
      authenticateWithGoogleIdToken(token);
    });
  }

  async function fetchAuthConfig() {
    try {
      const res = await fetch('/api/v1/auth/config');
      if (res.ok) {
        const config = await res.json();
        state.googleClientId = config.google_client_id;
        setupGoogleSignInButton();
      }
    } catch (e) {
      console.warn('Failed to load auth config:', e);
    }
  }

  function setupGoogleSignInButton() {
    if (!state.googleClientId) {
      if (el.googleBtnTarget) {
        el.googleBtnTarget.innerHTML = `
          <div class="google-notice">
            <span>Google Sign-In ready.</span>
            <small>Configure GOOGLE_CLIENT_ID in Cloud Run to enable the one-click Google button, or use direct token authentication below.</small>
          </div>
        `;
      }
      return;
    }

    function tryRender() {
      if (window.google && window.google.accounts && window.google.accounts.id) {
        google.accounts.id.initialize({
          client_id: state.googleClientId,
          callback: (resp) => {
            if (resp && resp.credential) {
              authenticateWithGoogleIdToken(resp.credential);
            }
          },
        });
        google.accounts.id.renderButton(el.googleBtnTarget, {
          theme: 'outline',
          size: 'large',
          width: 280,
          text: 'signin_with',
          shape: 'rectangular',
        });
      } else {
        setTimeout(tryRender, 200);
      }
    }
    tryRender();
  }

  el.btnLogout.addEventListener('click', logout);

  async function logout() {
    try {
      const headers = {};
      const csrf = csrfCookie() || state.csrfToken;
      if (state.token) headers['Authorization'] = `Bearer ${state.token}`;
      if (csrf) headers['X-CSRF-Token'] = csrf;
      const res = await fetch('/api/v1/auth/logout', { method: 'POST', credentials: 'same-origin', headers });
      if (!res.ok && res.status !== 401) throw new Error('Logout failed');
    } catch (e) {
      // Retain the session until the server confirms logout; allow a safe retry.
      alert('Could not log out. Please retry.');
      return;
    }
    clearLocalSession();
  }

  function clearLocalSession() {
    applicationManager?.reset();
    state.token = null;
    state.csrfToken = null;
    state.user = null;
    state.analyticsRequest++;
    el.recentBody.replaceChildren?.();
    localStorage.removeItem('ap_admin_token');
    localStorage.removeItem('ap_csrf_token');
    if (state.refreshTimer) clearInterval(state.refreshTimer);
    if (window.google && window.google.accounts && window.google.accounts.id) {
      google.accounts.id.disableAutoSelect();
    }
    el.dashboardContainer.classList.add('hidden');
    el.loginContainer.classList.remove('hidden');
  }

  // --- Environment & App Selection ---
  document.getElementById('nav-analytics')?.addEventListener('click', () => showSection('analytics'));
  document.getElementById('nav-applications')?.addEventListener('click', () => showSection('applications'));

  function showSection(section, refresh = true) {
    state.section = section;
    state.analyticsRequest++;
    applicationManager?.leaveSection();
    document.getElementById('application-management')?.classList[section === 'applications' ? 'remove' : 'add']('hidden');
    document.getElementById('analytics-view')?.classList[section === 'analytics' ? 'remove' : 'add']('hidden');
    for (const name of ['analytics', 'applications']) {
      const button = document.getElementById(`nav-${name}`);
      if (button) {
        button.className = `btn ${name === section ? 'btn-secondary' : 'btn-outline'}`;
        button.setAttribute?.('aria-current', name === section ? 'page' : 'false');
      }
    }
    el.appSelector.disabled = section !== 'analytics';
    el.dateRangeFilter.disabled = section !== 'analytics';
    el.btnExportCsv.disabled = section !== 'analytics';
    if (section === 'analytics' && refresh && state.user) fetchDashboardData();
  }

  el.envLive.addEventListener('click', () => switchEnvironment('live'));
  el.envTest.addEventListener('click', () => switchEnvironment('test'));

  function switchEnvironment(env) {
    state.analyticsRequest++;
    el.recentBody.replaceChildren?.();
    state.selectedEnv = env;
    if (env === 'live') {
      el.envLive.classList.add('active');
      el.envTest.classList.remove('active');
      el.testBanner.classList.add('hidden');
    } else {
      el.envTest.classList.add('active');
      el.envLive.classList.remove('active');
      el.testBanner.classList.remove('hidden');
    }
    fetchDashboardData();
  }

  el.appSelector.addEventListener('change', (e) => {
    state.analyticsRequest++;
    el.recentBody.replaceChildren?.();
    state.selectedApp = e.target.value;
    fetchDashboardData();
  });

  el.dateRangeFilter.addEventListener('change', (e) => {
    state.selectedRange = e.target.value;
    el.chartRangeLabel.textContent = el.dateRangeFilter.options[el.dateRangeFilter.selectedIndex].text;
    fetchDashboardData();
  });

  // --- Date Range Calculation ---
  function getDateParams() {
    const now = new Date();
    let start = new Date();
    if (state.selectedRange === 'today') {
      start.setHours(start.getHours() - 24);
    } else if (state.selectedRange === '7d') {
      start.setDate(start.getDate() - 7);
    } else if (state.selectedRange === '30d') {
      start.setDate(start.getDate() - 30);
    } else if (state.selectedRange === '90d') {
      start.setDate(start.getDate() - 90);
    }
    return {
      start_date: start.toISOString(),
      end_date: now.toISOString(),
    };
  }

  async function refreshApplications(preferredId) {
      const appsRes = await apiRequest('/api/v1/apps');
      if (!appsRes.ok) throw new Error('Failed to load apps');
      state.apps = await appsRes.json();
      applicationManager?.setApps(state.apps);
      const active = state.apps.filter(app => !app.status || app.status === 'ACTIVE');
      const previous = state.selectedApp;
      state.selectedApp = active.find(app => app.app_id === (preferredId || state.selectedApp))?.app_id || active[0]?.app_id || null;
      if (state.selectedApp !== previous) { state.analyticsRequest++; el.recentBody.replaceChildren?.(); }
      el.appSelector.innerHTML = active.map(a => `<option value="${escapeHtml(a.app_id)}">${escapeHtml(a.name)} (${escapeHtml(a.app_id)})</option>`).join('');
      el.appSelector.value = state.selectedApp || '';
      document.getElementById('analytics-content')?.classList[active.length ? 'remove' : 'add']('hidden');
      document.getElementById('application-empty')?.classList[active.length ? 'add' : 'remove']('hidden');
  }

  // --- Init Dashboard ---
  async function initDashboard() {
    try {
      applicationManager?.setUser(state.user);
      await refreshApplications();
      showSection('analytics', false);

      // Display user info
      el.userDisplay.textContent = state.user?.email || 'Authenticated';
      el.loginContainer.classList.add('hidden');
      el.dashboardContainer.classList.remove('hidden');

      // 2. Fetch initial dashboard data
      await fetchDashboardData();

      // 3. Poll every 15s
      if (state.refreshTimer) clearInterval(state.refreshTimer);
      state.refreshTimer = setInterval(fetchDashboardData, 15000);
    } catch (err) {
      console.error(err);
      clearLocalSession();
    }
  }

  // --- Data Fetching & Rendering ---
  async function fetchDashboardData() {
    if (!state.selectedApp || state.section !== 'analytics') return;
    const requestId = ++state.analyticsRequest;
    const isCurrent = () => requestId === state.analyticsRequest && state.section === 'analytics';

    const { start_date, end_date } = getDateParams();
    const query = new URLSearchParams({
      app_id: state.selectedApp,
      environment: state.selectedEnv,
      start_date,
      end_date,
    }).toString();

    // 1. Overview KPIs
    try {
      const res = await apiRequest(`/api/v1/analytics/overview?${query}`);
      if (res.ok && isCurrent()) {
        const d = await res.json();
        if (!isCurrent()) return;
        renderKPI(el.kpiPageviews, el.kpiPageviewsDelta, d.pageviews.value, d.pageviews.change_pct, '%', d.pageviews.available);
        renderKPI(el.kpiVisitors, el.kpiVisitorsDelta, d.visitors.value, d.visitors.change_pct, '%', d.visitors.available, 'Absent identifiers');
        renderKPI(el.kpiSessions, el.kpiSessionsDelta, d.sessions.value, d.sessions.change_pct, '%', d.sessions.available, 'Absent identifiers');
        renderKPI(el.kpiBounce, el.kpiBounceDelta, `${d.bounce_rate.value}%`, d.bounce_rate.change_pct, '%', d.bounce_rate.available, 'Absent identifiers');
        renderKPI(el.kpiDuration, el.kpiDurationDelta, `${d.avg_duration_sec.value}s`, d.avg_duration_sec.change_pct, '%', d.avg_duration_sec.available, 'Absent identifiers');

        if (d.data_status === 'sample') {
          el.testBanner.textContent = 'Viewing synthetic sample dataset';
          el.testBanner.classList.remove('hidden');
        } else if (state.selectedEnv === 'test') {
          el.testBanner.textContent = 'You are viewing the TEST environment. Data is segregated from production.';
          el.testBanner.classList.remove('hidden');
        } else {
          el.testBanner.classList.add('hidden');
        }
      }
    } catch (e) { console.error('Overview error', e); }

    // 2. Timeseries
    try {
      const interval = state.selectedRange === 'today' ? 'hour' : 'day';
      const res = await apiRequest(`/api/v1/analytics/timeseries?${query}&interval=${interval}`);
      if (res.ok && isCurrent()) {
        const points = await res.json();
        if (!isCurrent()) return;
        renderTimeseriesChart(points);
      }
    } catch (e) { console.error('Timeseries error', e); }

    // 3. Top Pages
    try {
      const res = await apiRequest(`/api/v1/analytics/pages?${query}&limit=10`);
      if (res.ok && isCurrent()) {
        const pages = await res.json();
        if (!isCurrent()) return;
        if (!pages.length) {
          el.pagesBody.innerHTML = '<tr><td colspan="4" class="empty">No pageview data recorded</td></tr>';
        } else {
          el.pagesBody.innerHTML = pages.map(p => `
            <tr>
              <td><code>${escapeHtml(p.page_path)}</code></td>
              <td class="num font-bold">${p.views_count.toLocaleString()}</td>
              <td class="num">${p.visitors_count.toLocaleString()}</td>
              <td class="num">${p.avg_duration_sec}s</td>
            </tr>
          `).join('');
        }
      }
    } catch (e) { console.error('Pages error', e); }

    // 4. Referrers
    try {
      const res = await apiRequest(`/api/v1/analytics/referrers?${query}&limit=10`);
      if (res.ok && isCurrent()) {
        const refs = await res.json();
        if (!isCurrent()) return;
        if (!refs.length) {
          el.referrersBody.innerHTML = '<tr><td colspan="3" class="empty">No referral data recorded</td></tr>';
        } else {
          el.referrersBody.innerHTML = refs.map(r => `
            <tr>
              <td>
                <span>${escapeHtml(r.referrer_domain)}</span>
                ${r.referrer_category && r.referrer_category !== 'Direct / None' ? `<span class="badge-subtle">${escapeHtml(r.referrer_category)}</span>` : ''}
              </td>
              <td class="num font-bold">${r.views_count.toLocaleString()}</td>
              <td class="num">${r.visitors_count.toLocaleString()}</td>
            </tr>
          `).join('');
        }
      }
    } catch (e) { console.error('Referrers error', e); }

    // 5. Devices & Browsers
    try {
      const res = await apiRequest(`/api/v1/analytics/devices?${query}`);
      if (res.ok && isCurrent()) {
        const data = await res.json();
        if (!isCurrent()) return;
        renderBreakdownList(el.deviceList, data.devices);
        renderBreakdownList(el.browserList, data.browsers);
      }
    } catch (e) { console.error('Devices error', e); }

    // 6. Geography
    try {
      const res = await apiRequest(`/api/v1/analytics/geo?${query}&limit=10`);
      if (res.ok && isCurrent()) {
        const geo = await res.json();
        if (!isCurrent()) return;
        if (!geo.length) {
          el.geoBody.innerHTML = '<tr><td colspan="4" class="empty">No location data recorded</td></tr>';
        } else {
          el.geoBody.innerHTML = geo.map(g => `
            <tr>
              <td><strong>${escapeHtml(g.country_code)}</strong></td>
              <td>${escapeHtml(g.city_name || 'Unknown')}</td>
              <td class="num">${g.visitors_count.toLocaleString()}</td>
              <td class="num font-bold">${g.pageviews_count.toLocaleString()}</td>
            </tr>
          `).join('');
        }
      }
    } catch (e) { console.error('Geo error', e); }

    // 7. Recent Events Feed
    try {
      const res = await apiRequest(`/api/v1/analytics/recent?app_id=${state.selectedApp}&environment=${state.selectedEnv}&limit=50`);
      if (res.ok && isCurrent()) {
        const recent = await res.json();
        if (!isCurrent()) return;
        if (!recent.length) {
          el.recentBody.innerHTML = '<tr><td colspan="6" class="empty">No recent events recorded</td></tr>';
        } else {
          renderRecentEvents(recent);
        }
      }
    } catch (e) { console.error('Recent events error', e); }
  }

  // --- Render Helpers ---
  function renderRecentEvents(events) {
    el.recentBody.replaceChildren();
    for (const event of events) {
      const row = document.createElement('tr');
      const date = new Date(event.timestamp);
      const timestamp = Number.isNaN(date.getTime()) ? 'Unknown' : date.toISOString();
      for (const text of [timestamp, event.event_type, event.event_name, event.page_path, event.source || 'Not reported']) {
        const cell = document.createElement('td'); cell.textContent = text; row.appendChild(cell);
      }
      const cell = document.createElement('td');
      const details = document.createElement('details'); details.className = 'event-details';
      const summary = document.createElement('summary'); summary.textContent = 'View details';
      const content = document.createElement('pre');
      content.textContent = JSON.stringify({ timestamp, event_name: event.event_name, event_type: event.event_type, page_path: event.page_path,
        source: event.source || 'Not reported', metadata: event.metadata || {}, duration_ms: event.duration_ms,
        country: event.country_code || 'Unknown', device: event.device_family || 'Unknown', browser: event.browser_family || 'Unknown' }, null, 2);
      details.appendChild(summary); details.appendChild(content); cell.appendChild(details); row.appendChild(cell); el.recentBody.appendChild(row);
    }
  }

  function renderKPI(valEl, deltaEl, val, delta, unit = '%', available = true, unavailableLabel = 'Not tracked') {
    if (available === false) {
      valEl.textContent = '—';
      deltaEl.textContent = unavailableLabel;
      deltaEl.className = 'kpi-delta unavailable';
      return;
    }
    valEl.textContent = typeof val === 'number' ? val.toLocaleString() : val;
    deltaEl.textContent = `${delta >= 0 ? '+' : ''}${delta}${unit}`;
    deltaEl.className = `kpi-delta ${delta >= 0 ? 'pos' : 'neg'}`;
  }

  function renderBreakdownList(container, items) {
    if (!items || !items.length) {
      container.innerHTML = '<li class="empty" style="padding:0.5rem 0;">No data</li>';
      return;
    }
    container.innerHTML = items.map(item => `
      <li class="bar-item">
        <div class="bar-labels">
          <span>${escapeHtml(item.name)}</span>
          <span class="num">${item.percentage}%</span>
        </div>
        <div class="bar-track">
          <div class="bar-fill" style="width: ${Math.min(item.percentage, 100)}%;"></div>
        </div>
      </li>
    `).join('');
  }

  function renderTimeseriesChart(points) {
    if (!points || !points.length) {
      el.trendSvg.innerHTML = '<text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" fill="#64748b" font-size="12">No data points for selected interval</text>';
      return;
    }

    const width = 1000;
    const height = 200;
    const maxVal = Math.max(...points.map(p => p.pageviews), 5);
    const stepX = width / Math.max(points.length - 1, 1);

    let pathD = '';
    if (points.length === 1) {
      const y = height - (points[0].pageviews / maxVal) * (height - 30) - 15;
      pathD = `M 0.0 ${y.toFixed(1)} L ${width}.0 ${y.toFixed(1)}`;
    } else {
      pathD = points.map((p, i) => {
        const x = i * stepX;
        const y = height - (p.pageviews / maxVal) * (height - 30) - 15;
        return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
      }).join(' ');
    }

    const areaD = `${pathD} L ${width} ${height} L 0 ${height} Z`;

    const startDate = points[0]?.timestamp ? points[0].timestamp.split('T')[0] : '';
    const endDate = points[points.length - 1]?.timestamp ? points[points.length - 1].timestamp.split('T')[0] : '';

    el.trendSvg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    el.trendSvg.innerHTML = `
      <defs>
        <linearGradient id="grad" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.3" />
          <stop offset="100%" stop-color="#38bdf8" stop-opacity="0.0" />
        </linearGradient>
      </defs>
      <line x1="0" y1="${height - 15}" x2="${width}" y2="${height - 15}" stroke="rgba(148, 163, 184, 0.15)" stroke-dasharray="4" />
      <path d="${areaD}" fill="url(#grad)" />
      <path d="${pathD}" fill="none" stroke="#38bdf8" stroke-width="2.5" />
      <text x="12" y="${height - 2}" fill="#64748b" font-size="11">${startDate}</text>
      <text x="${width - 12}" y="${height - 2}" text-anchor="end" fill="#64748b" font-size="11">${endDate}</text>
    `;
  }

  // --- Export Action ---
  el.btnExportCsv.addEventListener('click', async () => {
    if (!state.selectedApp) return;
    const { start_date, end_date } = getDateParams();
    const query = new URLSearchParams({
      app_id: state.selectedApp,
      environment: state.selectedEnv,
      export_format: 'csv',
      start_date,
      end_date,
    }).toString();

    try {
      const res = await apiRequest(`/api/v1/analytics/export?${query}`, { method: 'POST' });
      if (!res.ok) throw new Error('Export failed');
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `analytics-${state.selectedApp}-${state.selectedEnv}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      alert('Failed to export CSV: ' + e.message);
    }
  });

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function formatTime(isoStr) {
    if (!isoStr) return '';
    const d = new Date(isoStr);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  }

  // --- Startup ---
  fetchAuthConfig();

  fetch('/api/v1/auth/me', {
    credentials: 'same-origin',
    headers: state.token ? { 'Authorization': `Bearer ${state.token}` } : {},
  })
    .then(async (res) => {
      if (res.ok) {
        state.user = await res.json();
        initDashboard();
      } else {
        clearLocalSession();
      }
    })
    .catch(() => {
      el.loginContainer.classList.remove('hidden');
    });
})();
