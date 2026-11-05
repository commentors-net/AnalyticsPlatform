# Analytics Platform — Initial API Contracts & Authentication Boundaries

## 1. Overview & Protocol Boundaries

The Analytics Platform exposes two strictly segregated API surfaces:
1. **Public Ingestion API (`/v1/*`):** High-throughput, public HTTPS endpoints for event collection from web browsers, mobile applications, and backend servers. Secured via write-only keys (`write_key`).
2. **Administrative Dashboard API (`/api/v1/*`):** Private, authenticated REST endpoints for dashboard analytics visualization, tenant configuration, key rotation, compliance purging, and audited data exports. Secured via OIDC / JWT session authentication with RBAC.

---

## 2. Public Ingestion API Contracts

### 2.1 Single Event Ingestion: `POST /v1/events`

Dispatches a single telemetry or interaction event.

#### Headers:
- `Content-Type: application/json`
- `X-Write-Key: apk_live_9f2a4b8...` (or via payload `write_key`)
- `Origin: https://askanna.ai` (required for browser clients)

#### Request Body Schema:
```json
{
  "write_key": "apk_live_9f2a4b8c1234567890abcdef12345678",
  "event_id": "018f3a21-9980-7c22-bca8-f918903e1e91",
  "event_type": "pageview",
  "event_name": "page_view",
  "visitor_id": "vid_9f2a4b8c-1234-4567-890a-bcdef1234567",
  "session_id": "ses_a1b2c3d4-5678-90ab-cdef-1234567890ab",
  "page_path": "/dashboard/analytics",
  "referrer": "https://google.com/search",
  "duration_ms": 1450,
  "metadata": {
    "theme": "dark",
    "feature_flag_v2": true
  },
  "timestamp": "2026-11-01T15:20:00.000Z"
}
```

#### Field Constraints:
- `event_id`: Optional client UUIDv7 or UUIDv4 for deduplication. If omitted, the server assigns a UUIDv7.
- `visitor_id`: Optional pseudonymous UUID string. Omitted or `null` when client operates in `NO_STORAGE` mode.
- `session_id`: Optional session UUID. Omitted when in `NO_STORAGE` mode.
- `page_path`: Required string. Automatically sanitized server-side (query parameters matching sensitive keywords are stripped). Max length: 1,024 chars.
- `metadata`: Optional JSON object. Max size: 16 KB. Prohibited keys (`vin`, `ssn`, `password`, `token`, `chat_message`) are rejected with `422 Unprocessable Entity`.
- `timestamp`: ISO-8601 UTC timestamp. Server accepts timestamps within `[NOW - 24 hours, NOW + 5 minutes]` to prevent historical skew.

#### Success Response (`201 Created`):
```json
{
  "status": "success",
  "event_id": "018f3a21-9980-7c22-bca8-f918903e1e91",
  "persisted_at": "2026-11-01T15:20:00.042Z"
}
```

---

### 2.2 Batch Event Ingestion: `POST /v1/batch`

Accepts an array of events (maximum 50 events per batch, max payload size 512 KB).

#### Request Body Schema:
```json
{
  "write_key": "apk_live_9f2a4b8c1234567890abcdef12345678",
  "batch": [
    {
      "event_id": "018f3a21-9980-7c22-bca8-f918903e1e91",
      "event_type": "pageview",
      "event_name": "page_view",
      "page_path": "/home",
      "timestamp": "2026-11-01T15:19:50.000Z"
    },
    {
      "event_id": "018f3a21-9980-7c22-bca8-f918903e1e92",
      "event_type": "custom",
      "event_name": "button_click",
      "page_path": "/home",
      "metadata": { "button_id": "cta_signup" },
      "timestamp": "2026-11-01T15:19:55.000Z"
    }
  ]
}
```

#### Success Response (`202 Accepted`):
```json
{
  "status": "accepted",
  "processed_count": 2,
  "failed_count": 0,
  "persisted_event_ids": [
    "018f3a21-9980-7c22-bca8-f918903e1e91",
    "018f3a21-9980-7c22-bca8-f918903e1e92"
  ]
}
```

---

### 2.3 Health Probes
- `GET /health/live`: Returns `{"status": "ok"}` (Liveness probe for Cloud Run).
- `GET /health/ready`: Checks PostgreSQL connection pool health. Returns `{"status": "ready", "database": "connected"}` or `503 Service Unavailable`.

---

## 3. Administrative Dashboard API Contracts (`/api/v1/*`)

All administrative requests require a valid Bearer token (`Authorization: Bearer <JWT>`) or a verified session cookie.

### 3.1 Authentication & Session
- `GET /api/v1/auth/config`: Public Google authentication configuration. Returns the Web Client ID (first configured audience) for the dashboard button.
- `POST /api/v1/auth/google`: Verifies a Google ID token and requires an active, pre-approved account. Returns a short-lived application JWT (15 minutes) and sets Secure, HttpOnly, SameSite session cookies plus a readable CSRF cookie.
- `GET /api/v1/auth/me`: Reads the authenticated profile. Cookie-authenticated safe reads do not require a CSRF header.
- Cookie-authenticated mutations require `X-CSRF-Token` to match both the CSRF cookie and the signed JWT claim. Bearer-authenticated API calls do not require this browser CSRF token.
- `POST /api/v1/auth/logout`: Requires authentication (and CSRF for cookie auth). Durably revokes the presented token, then clears session/CSRF cookies. Replays of that token are rejected for both cookie and Bearer auth; other login sessions remain valid. A revocation-store failure returns 503 and does not report successful logout. Requests already executing cannot be recalled.
- Revocation records contain only a SHA-256 token digest as document ID and `expires_at`, under `analytics_users/{user_id}/revoked_sessions/{digest}` (or the configured analytics prefix). Each protected request checks shared revocation state and denies access if that check fails. No usable tokens are stored. Expired records may be removed after JWT expiry; automated expiry cleanup/TTL is not provisioned by this change and must be included in the retention/deletion runbook, including account deletion and backups. Do not delete unexpired revocations during rollback while the same JWT signing key is active.
- `POST /api/v1/auth/login` and `/api/v1/auth/token`: Retired, return 410. No refresh endpoint is implemented; obtain a new Google sign-in when the short-lived application session expires.

### 3.2 Tenant Application Management (SuperAdmin)
- `GET /api/v1/apps`: Lists all registered applications accessible to the calling user.
- `POST /api/v1/apps`: Registers a new tenant application (`SuperAdmin` only).
  - Body: `{"app_id": "roomlyst", "name": "Roomlyst App", "allowed_origins": "https://roomlyst.com"}`

Application management also accepts optional `live_origins` and `test_origins` (comma/newline-separated HTTPS origins, or HTTP localhost for development). Explicit environment fields use exact origin matching; an empty field disables browser origins for that environment. Existing records without these fields retain the legacy `allowed_origins` behavior until explicitly configured. Missing Origin remains supported for authenticated server collectors; origins are an abuse check, not authentication.

- `PATCH /api/v1/apps/{app_id}`: Updates name, origins and/or status (`ACTIVE`, `SUSPENDED`, `ARCHIVED`) for SuperAdmin or an administrator granted access to that app. Identifier changes, null/empty patches, blank names and unsafe origins are rejected. Deactivation stops ingestion and new key issuance; existing records/keys are retained. Reactivation restores otherwise active keys, so revoke keys separately if permanent invalidation is intended.
- App responses include `can_manage` computed from the current user's app grant. Add is SuperAdmin-only; Edit, Deactivate/Activate and key mutations are scoped to app administrators. A viewer cannot gain mutation access by manipulating the UI.
- The dashboard's Applications section supports an empty account, refreshes the active-app selector after registration/edit/status changes, and shows separate LIVE/TEST key lists. The Add form includes an AskAnna preset (`askanna`, `https://askanna.online`, `https://test.askanna.online`). This preset does not register or change a consumer site until Save calls the platform API.
- Analytics and Applications are separate navigation sections. Switching sections clears one-time keys and deletion confirmations. `classification` is explicitly declared (`REAL`, `SAMPLE`, `UNCLASSIFIED`); names and TEST keys are not sufficient to infer that a record is disposable. Existing records are not automatically relabeled or deleted.
- Key creation returns `Cache-Control: no-store` and the raw key only in its creation response. Key lists return prefixes/metadata only. The dashboard never stores raw keys in local/session storage, logs or URL parameters; it clears the temporary display on dismissal, app/environment change, page hide or logout, including in-flight late responses. Copying to the user's clipboard is explicit.

### Permanent application deletion (SuperAdmin only)

- `GET /api/v1/apps/{app_id}/deletion-preview` is read-only, requires SuperAdmin and returns a no-store impact summary, retention notice and signed confirmation token valid for ten minutes. It is tied to the exact ID/creation generation and is not an authentication token. Preview traversal is capped at 2,000 documents; `truncated=true` means lower-bound counts. Counts are a snapshot and can increase before confirmation.
- `DELETE /api/v1/apps/{app_id}` requires JSON `{"confirmation":"<exact app_id>","preview_token":"<preview receipt>"}`, SuperAdmin authentication, and normal cookie CSRF checks. No automatic deletion happens during preview, startup or polling. The UI requires impact review and exact identifier typing.
- A transaction pauses the app as `DELETING` and writes a minimal marker in `analytics_deletions/{app_id}`. Ingestion/session writes, key issuance/revocation, permission grants and app edits share transaction guards on the app record, so cleanup cannot be undone by a concurrent platform write. This requires all active writer revisions to use the new guards before the feature is enabled.
- Each confirmed DELETE cleans at most 100 app-owned documents. It queries keys, permissions and idempotency by exact `app_id`, traverses only the exact `analytics_data/{app_id}_live`, `analytics_data/{app_id}_test` and target catalog descendants, deletes children before parents, and rejects conflicting app ownership. Missing parent documents do not hide nested derived data. No collection-wide delete or app-name prefix matching is used. Deletion refuses non-`analytics_` namespaces.
- Response 202 (`status="deleting"`) explicitly means incomplete: click Continue cleanup, or load a fresh preview and resume later. There is no automatic worker/loop. Failure returns 409 (scope/receipt/state issue) or 503 (interruption), retains the paused catalog/marker and must not be treated as completion. A timeout may leave a partially cleaned app; retry is safe and resumable. Retrying an already completed deletion with the same unexpired receipt returns 200 with zero additional deletions.
- Final 200 (`status="deleted"`) is returned only after the enumerated live app scope is empty and a final transaction deletes the catalog, completes its marker and records a deletion audit. The identifier is permanently retired to prevent stale data/credentials attaching to a recreated app. Users/account sessions and immutable audit records are retained; no other app or shared collection is removed. Existing backups are outside this live operation and follow separately reviewed retention/deletion policy. Unattributed orphan documents outside these owned paths cannot safely be assigned to an app and are not swept globally.
- Real Firestore/emulator transaction, failure-retry and large-data latency verification is required before deployment. Do not roll back to a writer revision that ignores the deletion fence while a job is in progress. Removing a parent document alone does not delete subcollections; see [Firestore deletion behavior](https://firebase.google.com/docs/firestore/manage-data/delete-data) and [transaction semantics](https://firebase.google.com/docs/firestore/manage-data/transactions).

### Recent-event display and geography

`GET /api/v1/analytics/recent?app_id=...&environment=live|test` retains application RBAC/environment scoping and returns a display-safe projection. It includes a reported source only for reviewed source labels, a bounded metadata allowlist (technical booleans/counts/HTTP method/status), and validated event identity/time/type/family fields. It omits visitor/session IDs, masked/raw IP, free-form metadata and referrer content. Names reject obvious credential/PII forms; displayed path segments use a conservative reviewed static vocabulary and strip queries/fragments. Unknown/custom segments appear as `[hidden]`. The detail panel renders text, not executable HTML. This is not permission to ingest personal data; hosts still must emit only reviewed names/paths/properties.

Old geography mapped loopback/private transport addresses to `LO / DEV / Localhost`. Those addresses commonly occur in synthetic tests, proxies and backend SDK traffic and do not identify a visitor's location. There is no actual GeoIP lookup configured, so new resolution returns null for all addresses. Historical records without `geo_source="verified_coarse_lookup"`, including Localhost and old unproven country/city claims, render/group as Unknown. A provenance marker is server-owned, not an accepted event input field, and does not enable a lookup provider by itself. Legacy records are not rewritten by display requests; TEST is not automatically labeled as localhost and LIVE is not assumed to have known geography.

### 3.3 API Key Management (AppAdmin & SuperAdmin)
- `GET /api/v1/apps/{app_id}/keys?env=live`: Lists active keys (shows `prefix`, `name`, `status`, `created_at`; raw key is never stored or returned).
- `POST /api/v1/apps/{app_id}/keys`: Generates a new write key.
  - Body: `{"environment": "live", "name": "Production Web SDK Key"}`
  - Response: Returns plaintext key **once** (`"apk_live_9f2a..."`). Only the SHA-256 hash is saved.
- `DELETE /api/v1/apps/{app_id}/keys/{key_id}`: Immediately revokes key (`status = 'REVOKED'`).

### 3.4 Analytics Query & Metric Endpoints
All query endpoints require `app_id` and query parameter `env=test|live`.
- `GET /api/v1/apps/{app_id}/metrics/overview?env=live&start_date=2026-10-01&end_date=2026-10-31`:
  - Returns daily time-series: total pageviews, unique visitors, total sessions, bounce rate, average session duration.
- `GET /api/v1/apps/{app_id}/metrics/pages?env=live&limit=20`:
  - Returns top URL paths, pageview counts, unique visitor counts, average time on page.
- `GET /api/v1/apps/{app_id}/metrics/geo?env=live`:
  - Returns breakdown by country code and region.
- `GET /api/v1/apps/{app_id}/metrics/devices?env=live`:
  - Returns breakdown by device family (desktop/mobile/tablet), OS, and browser.
- `GET /api/v1/apps/{app_id}/visitors/{visitor_id}/timeline?env=live`:
  - Restricted to `SuperAdmin` and `AppAdmin`. Returns chronological events for a specific pseudonymized visitor (retained within 90-day window).

### 3.5 Audited Data Export: `POST /api/v1/apps/{app_id}/export`
- **Permissions:** Restricted to `SuperAdmin` and `AppAdmin`.
- **Query Body:**
  ```json
  {
    "environment": "live",
    "format": "csv",
    "start_time": "2026-10-01T00:00:00Z",
    "end_time": "2026-10-31T23:59:59Z",
    "event_type": "pageview"
  }
  ```
- **Audit Requirement:** The system automatically logs the export operation to `audit_logs` including caller user ID, IP address, query parameters, and row count before streaming results.

### 3.6 Privacy Deletion: `POST /api/v1/apps/{app_id}/privacy/delete-visitor`
- **Permissions:** `SuperAdmin` or `AppAdmin`.
- **Body:** `{"visitor_id": "vid_9f2a4b8c-..."}`
- **Action:** Scans active partitions, sets `visitor_id = 'DELETED_ANONYMIZED'`, strips user metadata, and writes an audit event.

---

## 4. Error Responses & Standard Error Model

All error responses return a RFC 7807 Problem Details compatible structure:

```json
{
  "type": "https://analytics-platform.internal/errors/invalid-write-key",
  "title": "Invalid Ingestion Key",
  "status": 401,
  "detail": "The provided write_key does not match an active key in this environment.",
  "instance": "/v1/events"
}
```

### HTTP Status Code Usage:
- `200 OK`: Successful synchronous read or update.
- `201 Created`: Single event successfully committed to database.
- `202 Accepted`: Batch request accepted and committed.
- `400 Bad Request`: Malformed JSON or syntax failure.
- `401 Unauthorized`: Missing or invalid authentication token or `write_key`.
- `403 Forbidden`: Insufficient RBAC permission or unauthorized cross-tenant attempt.
- `413 Payload Too Large`: Payload exceeds size bounds (> 64 KB single, > 512 KB batch).
- `422 Unprocessable Entity`: Schema validation failure or prohibited fields (VIN, PII).
- `429 Too Many Requests`: Rate limit threshold exceeded. Includes `Retry-After: 60`.
- `500 Internal Server Error`: Server failure. Handled fail-open by client SDKs.
- `503 Service Unavailable`: Database unreachable or connection pool exhausted.
