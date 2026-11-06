# Python integration guide

This folder contains a Flask example and configuration/reference material for the **existing SDK in `sdk/python/`**, version `0.1.0`. It creates no cloud resources and does not change any consumer application. Use it as a reference when integrating a separately authorized host application.

The instructions follow `sdk/python/analytics/client.py`, its `pyproject.toml`, the current ingestion routes/schemas and the deployment manifest. The old SDK README still says implementation is planned; some older architecture contracts also differ from current code. The behavior below is taken from the code, not those older claims.

## Install from this repository

The distribution is named `analytics-python`; its import package is `analytics`. Install **this local source**, not an unrelated same-named package from a public index. The SDK is not bundled into this integration folder, so copy/distribute the audited `sdk/python/` source or a wheel built from it with the example.

From the AnalyticsPlatform repository root, use a dedicated Python environment:

```powershell
python -m venv .venv-integration
.\.venv-integration\Scripts\python.exe -m pip install "./sdk/python[flask]"
.\.venv-integration\Scripts\python.exe -c "import analytics.client; print(analytics.client.__file__)"
```

On Linux/macOS, use `python3 -m venv .venv-integration` and `.venv-integration/bin/python` for the remaining commands. The printed module path should resolve to this SDK's installed copy. The SDK declares Python >=3.9, depends on `httpx>=0.25.0`, and its Flask extra declares `flask>=2.0.0`. The example is verified with Python 3.10, Flask 3.1.2 and HTTPX 0.28.1; dependency locking in the host application remains the host's responsibility.

`env.example` is a template, not a file loaded by the example. Set its variables in your process environment or existing secret injection. No client secret, service-account credential, Google identity token or dashboard session token is needed for collection.

## Configure TEST first

| Variable | Meaning |
|---|---|
| `ANALYTICS_ENDPOINT` | Base URL, without `/dashboard`, query string or endpoint suffix. Default is the service URL below. HTTPS required, except HTTP localhost for local testing. |
| `ANALYTICS_ENVIRONMENT` | `test` (default) or `live`. This is example configuration, not an SDK constructor argument. |
| `ANALYTICS_ENABLED` | Explicitly set `true` to enable the example. Missing/other values leave it disabled. |
| `ANALYTICS_WRITE_KEY_TEST` | TEST collection key, beginning `apk_test_`. Blank in the template. |
| `ANALYTICS_WRITE_KEY_LIVE` | Separate LIVE collection key, beginning `apk_live_`. Blank in the template. |

The example selects the matching key and disables telemetry on missing/mismatched configuration. It does not log the key or configuration values. Start with TEST; switching to LIVE requires both the explicit environment setting and its distinct key.

The shared service URL reported in the latest deployment handoff and recorded in `infra/gcp/cloudrun-unified.yaml` is:

```text
https://analytics-platform-427212681311.us-central1.run.app
```

The prompt 17 deployment report records revision `analytics-platform-00005-f9r` using image tag `20261104-app-management`. This integration task does not independently certify the currently served revision or modify it.

An approved administrator obtains collection keys in the dashboard's **Applications → Collection keys** panel. Select the application and environment; copy a newly generated key from its one-time display into the host's secret configuration. Raw keys cannot be recovered from the list later. Rotate/revoke through the same panel. Never commit keys, put them in URLs, expose them in exception output, or pass them as visible command-line arguments.

The application and environment are resolved from the key. There is **no `app_id` or `environment` SDK constructor/`track()` argument**, and adding these fields to an event does not select a tenant. The current schema rejects extra event fields. The handoff reports AskAnna registered as `askanna`, with LIVE origin `https://askanna.online` and TEST origin `https://test.askanna.online`; this example does not register or edit it.

## Collection authentication and endpoints

The Python SDK sends JSON to `POST /v1/events/batch` using:

```text
Authorization: Bearer <the selected collection write key>
Content-Type: application/json
```

The server also accepts `X-Write-Key` or a JSON `write_key`; precedence is nonempty X-Write-Key, a Bearer collection key, then body key. A query-string key is not collection authentication. Ordinary Python calls omit `Origin` and do not require CORS or Google Sign-In. Do not forward browser cookies, Google tokens, authentication headers, raw client IP or request bodies to the collector.

These are server-originated events. When using server middleware (e.g. Flask/FastAPI), the host application can forward the visitor's `user_agent` and coarse `country_code` (e.g. from edge proxy headers such as `CF-IPCountry` or `X-AppEngine-Country`) to accurately attribute device, browser, and country metrics. If omitted, the collector safely attributes server provenance and maps `source="python"`. Reusing existing pseudonymous IDs under approved consent policies enables unique visitor and session tracking; absent identifiers are accurately presented as uncollected metrics rather than misleading zero counts.

If a browser Origin is supplied, explicit `live_origins`/`test_origins` settings match exactly by environment (scheme, hostname, port). Missing Origin is allowed for server collectors. Legacy app records without scoped origins use the older shared-origin behavior. Origin checks are abuse checks, not a substitute for the write key.

| Endpoint | Actual role |
|---|---|
| `POST /v1/events` | Single event; JSON body limit 65,536 bytes; new event 201, recognized duplicate 200. |
| `POST /v1/events/batch` | SDK target; `{"batch": [...]}`, at most 50 events and 524,288 bytes; normally 202. |
| `POST /v1/batch` | Alias of the batch handler. |
| `GET /health/live` | Public liveness (`{"status":"ok"}`); does not establish ingestion or persistence. |
| `GET /health/ready` | Firestore readiness check; its implementation writes an analytics health document. Do not treat it as a zero-write test. |

There is no `/v1/beacon` route in the inspected implementation: browser Beacon uses the batch route with text/plain JSON. There is no `/v1/health` route; those names appear in older material. The batch schema also accepts `events` as an alias when `batch` is absent; use `batch`, as the SDK does. See [EVENT_REFERENCE.md](EVENT_REFERENCE.md) for wire fields/responses.

Dashboard administration is separate: `/api/v1/auth/google` verifies Google identity, then issues an application session for an explicitly approved account. Protected `/api/v1/*` endpoints use that app session/Bearer token and RBAC; cookie mutations require CSRF. A collection key grants no dashboard access. Conversely, an administrator JWT/Google ID token is not a collection key. The Flask example performs no administrative login or key management.

## Run the Flask example

With environment variables configured, run from the repository root:

```powershell
.\.venv-integration\Scripts\python.exe integrations/python/flask_example.py
```

The development server binds only `127.0.0.1:5000` with debug/reloader disabled. Open `/` for one pageview, `POST /action` for one `example_action` custom event, and `/health` for an untracked health response. `/action` is a demonstration, not a business transaction. No request body, headers, query strings or raw user paths are copied to analytics. Page paths are fixed `"/"` and `"/action"`; metadata is the fixed non-identifying `{"source":"flask_example"}`.

`create_app()` stores its optional client at `app.extensions["analytics_client"]` for controlled lifecycle/testing. This is an example extension slot, not an SDK feature. Create the app/client **inside each serving worker process**; do not create an enabled threaded client before a prefork server forks it. The Flask reloader/preload pattern can otherwise duplicate workers or inherit a non-running thread. The SDK already registers `close()` with `atexit`; a host may also call its client's `close()` in its own worker shutdown hook. Do not flush or close it after each Flask request.

Analytics initialization/tracking failures are caught so the host response still succeeds. Invalid/disabled configuration creates no SDK client. Missing required Python dependencies are installation errors that must be resolved before importing the example.

The example deliberately does **not** attach automatic SDK middleware: the existing `FlaskAnalytics` extension collects request path, referrer and user-agent metadata. Hosts with dynamic/secret-bearing URLs should review/redact those sources before opting into automatic request collection. This minimal example instead emits only its two explicitly selected events, avoiding duplicate pageviews and implicit URL collection.

## Reuse existing visitor/session functionality (optional)

No tracking IDs are required. The default example passes `visitor_id=None` and `session_id=None`. It does not read/write Flask `session`, cookies or browser storage; it does not start sessions, generate visitor IDs, fingerprint people or hash personal data.

If the host already has a consent-aware, pseudonymous analytics identity, its existing trusted server middleware can expose these attributes on Flask `g` before a route runs:

| Example adapter attribute | Source/behavior |
|---|---|
| `g.analytics_consent` | Host's already evaluated analytics policy: `NO_STORAGE`, `ANONYMOUS`, or `ANALYTICS_ALLOWED`. Missing/unknown means no IDs. |
| `g.analytics_visitor_id` | Existing pseudonymous analytics ID, used only under `ANALYTICS_ALLOWED`. Nonempty string <=128 chars. |
| `g.analytics_session_id` | Existing non-secret analytics session label, used under `ANONYMOUS` or `ANALYTICS_ALLOWED`. Nonempty string <=128 chars. |

These names are explicit integration points in this example, not standard Flask/SDK APIs. Map your existing values; do not create a second identity system. The adapter checks consent and string length, **not whether values contain PII**. Never supply a login session cookie/JWT, email, phone, VIN, user/customer database identifier, user message or a hash of personal data as an analytics identifier. Do not trust arbitrary caller-provided ID/consent headers.

| Host consent decision | Visitor sent | Session sent |
|---|---|---|
| Missing, unknown, or `NO_STORAGE` | null | null |
| `ANONYMOUS` | null | existing permitted session or null |
| `ANALYTICS_ALLOWED` | existing permitted visitor or null | existing permitted session or null |

Omitting IDs does not disable event persistence. The current collector can create an internal fallback session record for an event with no session ID; this example supplies no browser continuity. If the host's policy requires **no telemetry at all**, skip the telemetry call or disable the example.

The Python SDK has no `setConsent()`, withdrawal API or per-event consent parameter. Consent is decided by the host before enqueueing. Events already queued/in flight are not retroactively scrubbed when the host changes its policy. If strict withdrawal cancellation is required, do not assume this SDK provides it; resolve that SDK work separately before adopting persistent identifiers. The running service is unchanged by this package.

## Existing SDK methods

Import `AnalyticsClient` or `AsyncAnalyticsClient` from `analytics.client` (both are also re-exported by `analytics`). Both constructors accept:

| Argument | SDK default |
|---|---|
| `endpoint`, `write_key` | Required strings |
| `batch_size` | 20 (clamped to at least 1, not capped at 50) |
| `flush_interval_sec` | 2.0 |
| `max_queue_size` | 1000 |
| `timeout_sec` | 4.0 |
| `enabled` | True; empty key disables sending |

Public synchronous methods are:

```python
client.track(
    event_name="example_action", event_type="custom", page_path="/action",
    visitor_id=None, session_id=None, referrer=None, duration_ms=None,
    metadata={"source": "flask_example"}, timestamp=None,
)
client.pageview("/", visitor_id=None, session_id=None, referrer=None, metadata=None)
client.flush()
client.close()
```

`timestamp` for `track()` is a `datetime.datetime`, preferably timezone-aware UTC; the SDK serializes it. `pageview()` emits event name `pageview`, type `pageview`; it has no `timestamp` or `duration_ms` parameter. `track()` generates a fresh UUID4 event ID; neither method accepts caller-supplied `event_id`.

The async class has the same constructor/track/pageview arguments. Its `track`, `pageview`, `flush`, `close` methods must be awaited inside the application's running event loop; do not create a fresh loop per Flask request. It starts lazily on first track. Flask example uses the synchronous background-thread client. The existing extension is `analytics.middleware.flask.FlaskAnalytics`; the ASGI middleware is `analytics.middleware.fastapi.AnalyticsMiddleware`.

Methods return `None`, not a receipt or delivery acknowledgment. No public `identify`, `batch`, `capture`, `setConsent`, `health`, `retry`, context-manager or environment-selection method is implemented. Do not infer a method from another analytics library with the same package name.

## Delivery limits of the current implementation

The SDK favors host availability and is **best effort**:

- `track()` queues in memory; process exit/queue pressure/network failure can lose events. The oldest queued item is dropped at capacity. This is not a durable client queue.
- Failed/non-success batches are not retried or requeued; there is no public success callback. Recalling `track()` creates a new event ID, so it is not an idempotent retry of the original event.
- The worker honors `batch_size`, but manual `flush()` drains up to **100** items per request, exceeding the server's **50** limit. `close()` calls `flush()` too. A low worker batch size alone does not fix this path. Byte size is not capped by the SDK.
- The sync worker can also lose a partially collected batch around its timing/shutdown boundary. Shutdown is not a guaranteed drain. Async cancellation/close behavior is not a durable-delivery guarantee either.
- The example's `batch_size=1`, `max_queue_size=1` keeps its bounded events below count/byte limits at the cost of intentional drops under load. It is a low-volume demonstration, not a throughput or losslessness recommendation. Do not increase limits without separately reviewing/fixing the SDK's send/flush paths.
- The SDK does not sanitize metadata/URLs before transmission. Server rejection/redaction happens after receipt and is not permission to send PII/secrets. The example uses fixed safe paths/metadata and sets the `analytics` logger to WARNING; SDK DEBUG messages can include rejected server response text/exception details.

Do not use analytics as a business-action acknowledgment, audit ledger or exactly-once delivery mechanism. A failed analytics request must not block or roll back a host business action. These limitations are documented without changing the SDK or service in this task.

## Verification

The example was exercised with Flask's test client, the real local SDK and a mock HTTP transport, followed by requests through the current FastAPI ingestion contract with mock Firestore. Checks cover pageview/custom wire payloads, Bearer collection auth, fixed safe data, default/no-ID behavior, existing consent-scoped IDs, TEST/LIVE key selection, key-prefix mismatch, disabled/setup/network/tracking failure behavior and untracked health. This is local contract verification, not a real Cloud Run/Google-account test.

To reproduce the repository's SDK/ingestion baseline offline:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest tests/unit/test_python_sdk.py tests/integration/test_sdk_ingestion.py tests/integration/test_application_management.py -q -p no:cacheprovider
```

For a separately authorized host verification, use its TEST key and harmless fixed events first. Confirm the event in that application's TEST dashboard, and confirm LIVE metrics remain separate. A 200 Flask response or `track()` returning `None` alone does not prove delivery. Use a manually constructed TEST request if HTTP status/body evidence is needed; never print its key. Interpret 401 as invalid/revoked/expired key or inactive app, 403 as disallowed Origin, 413 as body size, 422 as payload/privacy constraints, 429 as rate limiting (`Retry-After`), and 5xx/network errors as collector failure. The SDK returns none of those responses to the caller.

No live write verification is performed by this documentation task. Integrating a consumer application, generating keys, modifying deployments or sending synthetic live telemetry requires its own explicitly authorized task.
