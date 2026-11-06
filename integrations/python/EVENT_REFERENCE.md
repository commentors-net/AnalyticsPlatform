# Event reference

Source: current `api/app/schemas/event.py`, `api/app/models/event.py`, `api/app/routes/events.py`, `api/app/core/dependencies.py` and `sdk/python/analytics/client.py`. These are **wire** contracts; a wire field is not automatically an SDK keyword argument.

## Types and names

| `event_type` | Meaning | Python SDK call |
|---|---|---|
| `pageview` | Page view; increments the server session's pageview counter. | `client.pageview("/")` emits name `pageview`; or `track("page_view", event_type="pageview", page_path="/")`. |
| `custom` | Named application action; does not increment pageviews. | `track("example_action", event_type="custom", page_path="/action")`. |
| `click` | Click/action category; does not increment pageviews. | `track("primary_button", event_type="click", page_path="/")`. |
| `timing` | Duration measurement; does not increment pageviews. Updates session duration and engagement metrics (e.g. `homepage_engagement` with `duration_ms>=10000` is non-bounce). | `track("homepage_engagement", event_type="timing", page_path="/", duration_ms=15000)`. |

These four lowercase enum values are supported. An event name is independently chosen by the host; no predefined commerce/login/chat event schema or automatic business hook is implemented. Use fixed names, not names containing personal data or user text. Direct single-event requests default the type to `pageview`; Python `track()` defaults it to `custom`.

## Event fields

| Field | Actual ingestion constraint/default | SDK behavior |
|---|---|---|
| `event_name` | Required, string length 1–128. | Required positional/keyword for `track`; pageview helper uses `pageview`. |
| `page_path` | Required, string length 1–1,024. | `track()` substitutes `/` when omitted/falsey; `pageview()` requires a path. Use a fixed safe route without personal/secret path components. |
| `event_type` | `pageview`, `custom`, `click`, `timing`; default `pageview`. | `track` default `custom`. |
| `event_id` | Optional UUID; server generates UUID4 if absent. The validator accepts standard UUID representations. | SDK generates a new UUID4 per call; no public override parameter. |
| `timestamp` | Optional ISO-8601 datetime; default server UTC now. Accepted range: 30 days past through 15 minutes future. Naive inputs normalize to UTC. | SDK serializes an aware UTC current time by default; `track(timestamp=...)` expects a Python datetime, not an ISO string. |
| `visitor_id` | Optional/null string, at most 128 chars. No UUID format is enforced. | Passed through; default null. When absent, metrics accurately distinguish absent identifiers from zero unique visitors. Only reuse an existing permitted pseudonymous analytics ID under applicable consent conditions. |
| `session_id` | Optional/null string, at most 128 chars. No UUID format is enforced. | Passed through; default null. When absent, session metrics reflect absent identifiers. Do not supply an authentication credential. |
| `referrer` | Optional/null string, at most 1,024 chars; server extracts a coarse domain and classifies category (Search, Social, Internal, Referral). | Passed through, default null. Prefer null or a reviewed domain; never pass a secret-bearing URL. |
| `duration_ms` | Optional/null integer >=0. | Supported on both `track()` and `pageview()`. For single-page websites, sessions with duration >= 10s or user interaction events are accurately classified as engaged (non-bounce). |
| `source` | Optional string, at most 64 chars, e.g. `python`, `server`, `browser`. | Passed through; defaults to `python` in Python SDK. Display projection maps technical source attributes, eliminating 'Not reported'. |
| `user_agent` | Optional string, at most 512 chars. Client browser user agent forwarded by server applications. | Supported on `track()` and `pageview()`. Allows server-side applications (like AskAnna) to record the visitor's real browser/device classification instead of the Python HTTP client. |
| `country_code` | Optional 2-letter uppercase ISO-3166-1 alpha-2 code (e.g. `US`, `MY`, `SG`, `GB`). Rejects synthetic `LO`, `ZZ`, `XX`. | Supported on `track()` and `pageview()`. Used when the host application or edge proxy (e.g. `CF-IPCountry`, `X-AppEngine-Country`) has trustworthy coarse country information. |
| `device_family` | Optional reviewed category (`desktop`, `mobile`, `tablet`, `bot`, `unknown`, `Other`). | Supported on `track()`. Validated against reviewed categories. Also reconciled from `metadata.client_device` or top-level `client_device`. |
| `browser_family` | Optional reviewed category (`Chrome`, `Firefox`, `Safari`, `Edge`, `Opera`, `Mobile Safari`, `Chrome Mobile`, `Other`, `unknown`). | Supported on `track()`. Validated against reviewed categories. Also reconciled from `metadata.client_browser` or top-level `client_browser` (case-normalized). |
| `os_family` | Optional reviewed category (`Windows`, `Linux`, `Android`, `iOS`, `macOS`, `Other`, `unknown`). | Supported on `track()`. Validated against reviewed categories. |
| `referrer_category` | Optional coarse category (`Direct / None`, `Search`, `Social`, `Internal`, `Referral`). | Mapped automatically from `referrer` or reconciled from `metadata.referrer_category` / top-level `referrer_category`. Prevents collapsing privacy-stripped referrals into Direct / None. |
| `client_country` | Optional 2-letter uppercase ISO-3166-1 alpha-2 code from a trusted server resolver. | Reconciled from `metadata.client_country` or top-level `client_country`. Untrusted browser metadata and client headers are barred from verified visitor geography. |
| `metadata` | JSON object; default `{}`; recursive depth/prohibited-data validation. Overall request limit applies. | Passed through; no SDK-side privacy scrubber. Use small bounded reviewed properties. Consumer metadata such as AskAnna's `client_device`, `client_browser`, `referrer_category`, `client_country`, and `source="public_homepage_notification"` are preserved and safely attributed. |
| `write_key` | Optional body authentication for direct requests; headers take precedence. | Not an event keyword; SDK uses the constructor key in the Authorization header. |

Unknown **event** fields are strictly rejected (`extra="forbid"`). Do not send `app_id`, `environment`, `user_id`, `consent_status`, `is_returning`, raw IP, or administrative tokens as top-level client fields. The server resolves app/environment from the collection key.

The collector supports absent identifiers accurately: when callers supply no `visitor_id` (such as in `NO_STORAGE` privacy mode) or no `session_id`, the overview metrics API and dashboard distinguish unavailable metrics (`available: false`, rendered as `— / Absent identifiers`) from genuine zero values. Synthetic test data (`TEST` environment or `SAMPLE` classification) is explicitly marked via `data_status`.

## Privacy checks

Current metadata validation rejects nesting deeper than five recursive levels, including traversal through lists/scalars. It rejects the configured keys (case-insensitive/trimmed), keys containing `secret`, `password`, `credential`, keys ending `_email`, and strings matching its email pattern.

Configured exact keys at this snapshot:

```text
vin ssn password token chat_message credit_card secret secret_key auth
email contact_email phone gps latitude longitude id_token magic_link credential
api_key access_token refresh_token message msg user_message
```

These checks are rejection rules, not a guarantee of PII detection. Phone numbers, free text, personal data under other property names and sensitive path/query values must be excluded by the host **before transmission**. Do not send emails, phone numbers, VINs, user/chat messages, passwords, tokens, raw IP or precise GPS. Avoid unnecessary identifiers and arbitrary request bodies/headers.

The server redacts recognized query parameters, including `token`, `jwt`, `key`, `api_key`, `auth`, `password`, `passwd`, `secret`, `ssn`, `vin`, `email`, `mail`, `user`, `username`, `session`, `session_id`, `access_token`, `refresh_token`, `code`, `id_token`, `verification_code`, `magic_link`, from page URLs and hash-route queries. Other values/path segments are not comprehensively filtered. This does not prevent secrets from reaching the server first; use fixed safe paths as in the example.

## Requests and responses

SDK envelope (generated in memory, not a public `batch()` method):

```json
{
  "batch": [
    {
      "event_type": "custom",
      "event_name": "example_action",
      "page_path": "/action",
      "visitor_id": null,
      "session_id": null,
      "referrer": null,
      "duration_ms": null,
      "metadata": {"source": "flask_example"}
    }
  ]
}
```

The SDK also adds generated `event_id` and a current serialized `timestamp` to every event. They are omitted from this static example so copying it does not send a stale timestamp or repeatedly reuse one ID. The static envelope is accepted with a valid separately supplied collection key.

- Single route: `POST /v1/events`, JSON or text/plain JSON, at most 65,536 bytes.
- Batch routes: `POST /v1/events/batch` and `/v1/batch`, JSON or text/plain JSON, at most 524,288 bytes and 50 events in `batch`. The schema also accepts `events` as an alias when `batch` is absent, and currently permits an empty batch; neither is needed by the SDK.
- Keys belong to exactly one app/environment. Nonempty X-Write-Key takes precedence over a Bearer collection key, then body key (batch wrapper, or first event fallback). Never mix app/environment keys in one batch.
- Missing Origin works for server-to-server calls; a supplied Origin must satisfy the app/environment allowlist. Query-string credentials do not authenticate.
- New single-event success: 201, `{ "status": "success", "event_id": "<UUID>", "persisted_at": "<UTC timestamp>" }`. Recognized duplicate response uses 200 and the same shape.
- Batch success: 202, `{ "status": "accepted", "processed_count": 1, "failed_count": 0, "persisted_event_ids": ["<UUID>"] }`. `processed_count` includes already-seen IDs and is not a newly-inserted-row count.

Do not infer all-or-nothing batch atomicity, exactly-once delivery or distributed concurrency guarantees from these response names. Current batch ingestion loops through events and the Firestore repository performs separate persistence operations. A batch failure can occur after earlier events were written. The SDK has no built-in retries or exposed receipts. Do not implement retries by calling `track()` again and assume it preserves the original event ID.

Common failures: 401 key/app inactive, invalid, revoked or expired; 403 origin denied; 413 byte limit; 422 shape/type/timestamp/privacy validation; 429 rate limit with Retry-After; 5xx backend failure. Single/batch limits are streamed server-side; the SDK itself does not enforce payload-byte limits. Its manual flush can build 100-event requests, so follow the [delivery-limit notes](INTEGRATION_GUIDE.md#delivery-limits-of-the-current-implementation) rather than assuming SDK and server batch limits match.
