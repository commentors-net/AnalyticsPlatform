/* Application administration uses the existing authenticated API client. */
(function () {
  'use strict';

  class ApplicationManager {
    constructor({ apiRequest, onChanged }) {
      this.api = apiRequest;
      this.onChanged = onChanged;
      this.apps = [];
      this.user = null;
      this.editing = null;
      this.keyApp = null;
      this.environment = 'live';
      this.sequence = 0;
      this.session = 0;
      this.appBusy = false;
      this.keyBusy = false;
      this.el = {};
      for (const id of ['app-add', 'app-message', 'application-rows', 'app-form', 'app-form-title', 'app-name', 'app-id', 'app-live-origins', 'app-test-origins', 'app-save', 'app-preset', 'app-cancel', 'key-panel', 'key-title', 'key-close', 'keys-live', 'keys-test', 'key-environment-label', 'key-message', 'key-form', 'key-name', 'key-generate', 'key-once', 'key-once-label', 'key-value', 'key-copy', 'key-dismiss', 'key-rows']) {
        this.el[id] = document.getElementById(id);
      }
      this.el['app-add'].addEventListener('click', () => this.openForm());
      for (const id of ['app-classification', 'app-delete-panel', 'app-delete-title', 'app-delete-notice', 'app-delete-impact', 'app-delete-retained', 'app-delete-message', 'app-delete-form', 'app-delete-label', 'app-delete-confirmation', 'app-delete-submit', 'app-delete-cancel']) {
        this.el[id] = document.getElementById(id);
      }
      this.deleteSequence = 0;
      this.el['app-delete-form'].addEventListener('submit', event => this.deleteApplication(event));
      this.el['app-delete-cancel'].addEventListener('click', () => this.closeDeletion());
      this.el['app-delete-confirmation'].addEventListener('input', () => {
        this.el['app-delete-submit'].disabled = this.appBusy || this.el['app-delete-confirmation'].value !== this.deletePreview?.app_id;
      });
      this.el['app-cancel'].addEventListener('click', () => this.hideForm());
      this.el['app-preset'].addEventListener('click', () => {
        this.el['app-name'].value = 'AskAnna';
        this.el['app-id'].value = 'askanna';
        this.el['app-classification'].value = 'REAL';
        this.el['app-live-origins'].value = 'https://askanna.online';
        this.el['app-test-origins'].value = 'https://test.askanna.online';
      });
      this.el['app-form'].addEventListener('submit', event => this.save(event));
      this.el['key-form'].addEventListener('submit', event => this.generate(event));
      this.el['key-close'].addEventListener('click', () => this.closeKeys());
      this.el['keys-live'].addEventListener('click', () => this.switchKeys('live'));
      this.el['keys-test'].addEventListener('click', () => this.switchKeys('test'));
      this.el['key-dismiss'].addEventListener('click', () => this.clearSecret());
      this.el['key-copy'].addEventListener('click', async () => {
        const secret = this.el['key-value'].textContent;
        if (!secret) return;
        try {
          await navigator.clipboard.writeText(secret);
          this.el['key-message'].textContent = 'Key copied. Save it securely, then dismiss this display.';
        } catch {
          this.el['key-message'].textContent = 'Clipboard unavailable. Select the displayed key to copy it manually.';
        }
      });
      window.addEventListener('pagehide', () => this.clearSecret());
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'hidden') this.clearSecret();
      });
    }

    setUser(user) {
      this.user = user;
      this.el['app-add'].classList[user?.role === 'SuperAdmin' ? 'remove' : 'add']('hidden');
    }

    async json(url, options = {}) {
      const response = await this.api(url, options);
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(typeof error.detail === 'string' ? error.detail : `Request failed (${response.status}). Check the entered values.`);
      }
      return response.status === 204 ? null : response.json();
    }

    button(label, action, danger = false) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `btn btn-sm ${danger ? 'btn-danger' : 'btn-secondary'}`;
      button.textContent = label;
      button.addEventListener('click', action);
      return button;
    }

    cell(row, value) {
      const cell = document.createElement('td');
      cell.textContent = value;
      row.appendChild(cell);
      return cell;
    }

    setApps(apps) {
      this.apps = apps;
      this.el['application-rows'].replaceChildren();
      for (const app of apps) {
        const row = document.createElement('tr');
        const name = this.cell(row, `${app.name} (${app.app_id})`);
        const label = document.createElement('small');
        label.className = 'app-classification';
        label.textContent = ({ REAL: 'Real application (declared)', SAMPLE: 'Sample / test (declared)' })[app.classification] || 'Unclassified';
        name.appendChild(label);
        this.cell(row, app.status);
        this.cell(row, app.live_origins ?? app.allowed_origins ?? '');
        this.cell(row, app.test_origins ?? app.allowed_origins ?? '');
        const actions = this.cell(row, '');
        if (app.can_manage && app.status !== 'DELETING') {
          actions.appendChild(this.button('Edit', () => this.openForm(app)));
          actions.appendChild(this.button('Collection keys', () => this.openKeys(app)));
          actions.appendChild(this.button(app.status === 'ACTIVE' ? 'Deactivate' : 'Activate', () => this.changeStatus(app), app.status === 'ACTIVE'));
        } else {
          actions.textContent = app.status === 'DELETING' ? 'Deletion paused / in progress' : 'View only';
        }
        if (app.can_delete) actions.appendChild(this.button(app.status === 'DELETING' ? 'Resume deletion' : 'Delete permanently', () => this.openDeletion(app), true));
        this.el['application-rows'].appendChild(row);
      }
      if (!apps.length) this.el['application-rows'].textContent = 'No applications registered.';
    }

    openForm(app = null) {
      if ((app && !app.can_manage) || (!app && this.user?.role !== 'SuperAdmin')) return;
      this.closeKeys();
      this.closeDeletion();
      this.editing = app;
      this.el['app-form-title'].textContent = app ? 'Edit application' : 'Add application';
      this.el['app-name'].value = app?.name || '';
      this.el['app-id'].value = app?.app_id || '';
      this.el['app-id'].disabled = !!app;
      this.el['app-classification'].value = app?.classification || 'UNCLASSIFIED';
      this.el['app-live-origins'].value = (app?.live_origins ?? app?.allowed_origins ?? '').replace(/,/g, '\n');
      this.el['app-test-origins'].value = (app?.test_origins ?? app?.allowed_origins ?? '').replace(/,/g, '\n');
      this.el['app-preset'].classList[app ? 'add' : 'remove']('hidden');
      this.el['app-message'].textContent = '';
      this.el['app-form'].classList.remove('hidden');
      this.el['app-name'].focus();
    }

    hideForm() {
      this.el['app-form'].classList.add('hidden');
      this.el['app-form'].reset();
      this.editing = null;
    }

    async save(event) {
      event.preventDefault();
      if (this.appBusy || !this.user || !this.el['app-form'].reportValidity()) return;
      this.appBusy = true;
      this.el['app-save'].disabled = true;
      const session = this.session;
      const editing = this.editing;
      const payload = {
        name: this.el['app-name'].value.trim(),
        live_origins: this.el['app-live-origins'].value.trim(),
        test_origins: this.el['app-test-origins'].value.trim(),
        classification: this.el['app-classification'].value || 'UNCLASSIFIED',
      };
      if (!editing) payload.app_id = this.el['app-id'].value.trim();
      try {
        const app = await this.json(editing ? `/api/v1/apps/${encodeURIComponent(editing.app_id)}` : '/api/v1/apps', {
          method: editing ? 'PATCH' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
        });
        if (session !== this.session) return;
        this.hideForm();
        await this.onChanged(app.app_id);
        this.el['app-message'].textContent = 'Application saved.';
      } catch (error) {
        if (session === this.session) this.el['app-message'].textContent = error.message;
      } finally {
        this.appBusy = false;
        this.el['app-save'].disabled = false;
      }
    }

    async changeStatus(app) {
      if (this.appBusy || !confirm(`${app.status === 'ACTIVE' ? 'Deactivate' : 'Activate'} ${app.name}?`)) return;
      this.appBusy = true;
      this.closeKeys();
      const session = this.session;
      try {
        await this.json(`/api/v1/apps/${encodeURIComponent(app.app_id)}`, {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: app.status === 'ACTIVE' ? 'SUSPENDED' : 'ACTIVE' }),
        });
        if (session === this.session) await this.onChanged();
      } catch (error) {
        if (session === this.session) this.el['app-message'].textContent = error.message;
      } finally { this.appBusy = false; }
    }

    clearSecret() {
      this.secretVersion = (this.secretVersion || 0) + 1;
      this.el['key-value'].textContent = '';
      this.el['key-once-label'].textContent = '';
      this.el['key-once'].classList.add('hidden');
    }

    closeKeys() {
      this.sequence++;
      this.keyApp = null;
      this.clearSecret();
      this.el['key-rows'].replaceChildren();
      this.el['key-panel'].classList.add('hidden');
    }

    openKeys(app) {
      if (!app.can_manage) return;
      this.hideForm();
      this.closeDeletion();
      this.keyApp = app;
      this.el['key-title'].textContent = `${app.name} — collection keys`;
      this.el['key-panel'].classList.remove('hidden');
      return this.switchKeys('live');
    }

    async switchKeys(environment) {
      this.environment = environment;
      this.clearSecret();
      this.el['key-name'].value = '';
      this.el['key-message'].textContent = '';
      for (const env of ['live', 'test']) {
        this.el[`keys-${env}`].setAttribute('aria-pressed', String(env === environment));
        this.el[`keys-${env}`].className = `btn ${env === environment ? 'btn-secondary' : 'btn-outline'}`;
      }
      this.el['key-environment-label'].textContent = `${environment.toUpperCase()} collection keys`;
      this.el['key-form'].classList[this.keyApp?.status === 'ACTIVE' ? 'remove' : 'add']('hidden');
      return this.loadKeys();
    }

    async loadKeys() {
      const app = this.keyApp;
      if (!app) return;
      const seq = ++this.sequence;
      this.el['key-rows'].replaceChildren();
      try {
        const keys = await this.json(`/api/v1/apps/${encodeURIComponent(app.app_id)}/keys?env=${this.environment}`);
        if (seq !== this.sequence) return;
        for (const key of keys) {
          const row = document.createElement('tr');
          for (const value of [key.name, key.prefix, key.status, key.created_at]) this.cell(row, value);
          const actions = this.cell(row, '');
          if (key.status === 'ACTIVE') actions.appendChild(this.button('Revoke', async () => {
            if (!confirm(`Revoke ${key.name}?`)) return;
            this.clearSecret();
            try {
              await this.json(`/api/v1/apps/${encodeURIComponent(app.app_id)}/keys/${encodeURIComponent(key.id)}`, { method: 'DELETE' });
              if (seq === this.sequence) await this.loadKeys();
            } catch (error) { if (seq === this.sequence) this.el['key-message'].textContent = error.message; }
          }, true));
          this.el['key-rows'].appendChild(row);
        }
        if (!keys.length) this.el['key-rows'].textContent = 'No keys in this environment.';
      } catch (error) {
        if (seq === this.sequence) this.el['key-message'].textContent = error.message;
      }
    }

    async generate(event) {
      event.preventDefault();
      if (this.keyBusy || !this.keyApp || !this.user || !this.el['key-form'].reportValidity()) return;
      this.keyBusy = true;
      this.el['key-generate'].disabled = true;
      this.clearSecret();
      const seq = this.sequence;
      const secretVersion = this.secretVersion;
      const app = this.keyApp;
      const environment = this.environment;
      try {
        const key = await this.json(`/api/v1/apps/${encodeURIComponent(app.app_id)}/keys`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ environment, name: this.el['key-name'].value.trim() }),
        });
        if (seq !== this.sequence) return; // A dismissed/switched view cannot reveal an in-flight credential.
        await this.loadKeys();
        if (this.keyApp !== app || this.environment !== environment || this.secretVersion !== secretVersion) return;
        this.el['key-value'].textContent = key.raw_key;
        this.el['key-once-label'].textContent = `${app.name} — ${environment.toUpperCase()}`;
        this.el['key-once'].classList.remove('hidden');
      } catch (error) {
        if (this.keyApp === app) this.el['key-message'].textContent = error.message;
      } finally {
        this.keyBusy = false;
        this.el['key-generate'].disabled = false;
      }
    }

    closeDeletion() {
      this.deleteSequence++;
      this.deletePreview = null;
      this.el['app-delete-confirmation'].value = '';
      this.el['app-delete-submit'].disabled = true;
      this.el['app-delete-panel'].classList.add('hidden');
      this.el['app-delete-impact'].textContent = '';
      this.el['app-delete-message'].textContent = '';
    }

    leaveSection() {
      this.closeKeys();
      this.closeDeletion();
      this.hideForm();
    }

    async openDeletion(app) {
      if (!app.can_delete || this.user?.role !== 'SuperAdmin') return;
      this.closeKeys(); this.hideForm(); this.closeDeletion();
      const sequence = this.deleteSequence;
      try {
        const preview = await this.json(`/api/v1/apps/${encodeURIComponent(app.app_id)}/deletion-preview`);
        if (sequence !== this.deleteSequence) return;
        this.deletePreview = preview;
        this.el['app-delete-title'].textContent = `Permanently delete ${preview.name} (${preview.app_id})`;
        this.el['app-delete-notice'].textContent = preview.notice;
        this.el['app-delete-impact'].textContent = JSON.stringify({ catalog_documents: preview.catalog_documents, related_documents: preview.counts, counts_are_lower_bounds: preview.truncated }, null, 2);
        this.el['app-delete-retained'].textContent = preview.retained;
        this.el['app-delete-label'].textContent = `Type ${preview.app_id} to confirm deletion of LIVE and TEST data`;
        this.el['app-delete-submit'].textContent = preview.status === 'DELETING' ? 'Continue cleanup' : 'Delete permanently';
        this.el['app-delete-panel'].classList.remove('hidden');
        this.el['app-delete-confirmation'].focus();
      } catch (error) {
        if (sequence === this.deleteSequence) this.el['app-message'].textContent = error.message;
      }
    }

    async deleteApplication(event) {
      event.preventDefault();
      const preview = this.deletePreview;
      if (this.appBusy || this.user?.role !== 'SuperAdmin' || !preview || this.el['app-delete-confirmation'].value !== preview.app_id) return;
      const session = this.session;
      this.appBusy = true; this.el['app-delete-submit'].disabled = true;
      try {
        const result = await this.json(`/api/v1/apps/${encodeURIComponent(preview.app_id)}`, {
          method: 'DELETE', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ confirmation: this.el['app-delete-confirmation'].value, preview_token: preview.preview_token }),
        });
        if (session !== this.session) return;
        if (result.status === 'deleted') {
          this.closeDeletion();
          this.el['app-message'].textContent = 'Application deleted permanently. Its identifier is retired.';
        } else {
          this.el['app-delete-message'].textContent = result.message;
          this.el['app-delete-submit'].textContent = 'Continue cleanup';
        }
        await this.onChanged();
      } catch (error) {
        if (session === this.session) this.el['app-delete-message'].textContent = error.message;
      } finally {
        this.appBusy = false;
        this.el['app-delete-submit'].disabled = !this.deletePreview || this.el['app-delete-confirmation'].value !== this.deletePreview.app_id;
      }
    }

    reset() {
      this.session++;
      this.setUser(null);
      this.apps = [];
      this.closeKeys();
      this.closeDeletion();
      this.hideForm();
      this.el['application-rows'].replaceChildren();
      this.el['app-message'].textContent = '';
      this.el['key-message'].textContent = '';
    }
  }

  window.ApplicationManager = ApplicationManager;
})();
