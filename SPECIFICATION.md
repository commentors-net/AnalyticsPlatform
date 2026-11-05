# Analytics Platform — Authoritative System Specification

**Version:** 1.2  
**Status:** Living Authoritative Specification (M2 Baseline)  
**Classification:** Public Architecture & Engineering Specification

---

## 1. Executive Summary & Architecture Principles

The Analytics Platform is a standalone, high-performance, multi-tenant analytics engine designed to provide privacy-preserving first-party telemetry for consumer and enterprise applications. It is strictly segregated from consumer business applications, operating under dedicated infrastructure, identity boundaries, and least-privilege principles.

### Core Architectural Principles
1. **Privacy-by-Design & Zero-Fingerprinting:** No browser fingerprinting, no third-party tracking cookies, and no cross-site profiling. Strict three-tier consent (`NO_STORAGE`, `ANONYMOUS`, `ANALYTICS_ALLOWED`).
2. **Fail-Open Client Contract:** Telemetry operations must never block, degrade, or disrupt the host application. If network, storage, or telemetry services fail, host UX remains uninterrupted.
3. **Transactionally Durable Ingestion:** Events are committed to persistent storage (PostgreSQL) or an acknowledged durable queue before HTTP acknowledgment. In-memory-only acknowledged buffers are strictly prohibited.
4. **Defense-in-Depth Multi-Tenancy:** Hard tenant and environment isolation (`app_id` + `environment`) enforced by both API middleware and PostgreSQL Row-Level Security (RLS) on parent tables and individual child partitions.
5. **Least-Privilege Infrastructure:** Application services operate under dedicated, scoped IAM identities and unprivileged database roles (`NOBYPASSRLS`, zero `SUPERUSER`).

---

## 2. System Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                          CLIENT APPLICATIONS                           │
│  - Browser Applications (via @analytics/browser SDK)                  │
│  - Backend Services (via Python SDK / Direct REST API)                 │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │ HTTPS (POST /v1/events)
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        COLLECTOR / INGESTION API                       │
│  - FastAPI Ingestion Engine                                            │
│  - Write-Key Verification & SHA-256 Hashing                            │
│  - Origin Abuse Heuristic & CORS Preflight                             │
│  - Weighted Token-Bucket Rate Limiter                                  │
│  - Trusted-Proxy Client IP Extraction & Coarse GeoIP                   │
│  - Recursive Metadata & PII Sanitizer                                  │
│  - Idempotency & Deduplication Engine                                  │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │ Transactional SQL
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│                    POSTGRESQL 16 PERSISTENCE ENGINE                    │
│  - Ingestion Idempotency Registry (Unpartitioned, Composite PK)        │
│  - Events Table (Monthly Range Partitioning by Timestamp)              │
│  - Sessions Table (Composite Unique: app_id + env + session_id)        │
│  - Forced Row-Level Security (RLS) on all parent and child tables      │
│  - Rollup Aggregations (daily_page_metrics, daily_geo_metrics)         │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │ Scoped Queries (Tenant Session)
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      ADMIN & DASHBOARD PLATFORM                        │
│  - Authenticated REST API (JWT / OIDC + Platform RBAC)                 │
│  - Immutable Audit Logging for Data Access & Exports                   │
│  - Tenant-Scoped Metrics & Aggregations                                │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Data Ingestion & Collection Contract

### 3.1 Endpoints
- `POST /v1/events`: Ingest single telemetry event (Max body: 64 KB).
- `POST /v1/events/batch`: Ingest batch of telemetry events (Max batch size: 50 events; Max body: 512 KB).
- `GET /v1/health`: Unauthenticated service health check.

### 3.2 Authentication & Authorization
- Telemetry ingestion authenticates via scoped write keys:
  - Format: `apk_live_<hex32>` or `apk_test_<hex32>`.
  - Delivery: Transmitted via HTTP `Authorization: Bearer <key>` header or `X-Write-Key: <key>` header.
  - **Security Rule:** Collection keys are strictly forbidden in URL query strings to avoid leakages in proxy logs, browser histories, and referrer headers.
  - Verification: Fast lookup against SHA-256 key hash in `api_keys` table. Keys must be `status = 'active'` and `expires_at > NOW()`.
  - Allowed Origins: Ingestion checks host domain allowlist with dot-boundary matching.

### 3.3 Deduplication & Idempotency
- Events are identified by a client-provided UUIDv4 `event_id`.
- Deduplication is guaranteed globally across all time partitions via the non-partitioned `ingestion_idempotency` table:
  - Composite Primary Key: `(app_id, environment, event_id)`.
  - Ingestion attempts an atomic claim:
    ```sql
    INSERT INTO ingestion_idempotency (app_id, environment, event_id, status)
    VALUES (:app_id, :env, :event_id, 'processed')
    ON CONFLICT (app_id, environment, event_id) DO NOTHING
    RETURNING event_id;
    ```
  - If no row is returned, the event is recognized as a duplicate and silently discarded without re-processing, maintaining idempotent success (HTTP 200/202).

### 3.4 Rate Limiting & Abuse Prevention
- Rate limits are calculated via in-memory token-bucket algorithms:
  - Per write-key limit: 2,000 requests/minute.
  - Per IP address limit: 120 requests/minute.
- **Weighted Batch Cost:** Batch ingestion charges token buckets proportional to the number of events in the batch (`cost = len(events)`).
- **Trusted Proxy Extraction:** The client IP is extracted by walking `X-Forwarded-For` right-to-left against a verified list of `TRUSTED_PROXIES`. If the direct peer is untrusted, all forwarded headers are discarded.

---

## 4. Privacy, Identification & Consent Framework

### 4.1 Three-Tier Consent Model
The client SDK and backend support three explicit consent states:
1. `NO_STORAGE`:
   - Zero read/write access to browser `localStorage` or `sessionStorage`.
   - In-memory event dispatch only.
   - `visitor_id` and `session_id` are strictly `null`.
   - On transition to `NO_STORAGE`, any pending in-memory queue is immediately purged, active sessions are destroyed, and stored credentials/IDs are cleared.
2. `ANONYMOUS`:
   - Uses browser `sessionStorage` for ephemeral session continuity.
   - `visitor_id` is strictly `null`.
   - `session_id` is tracked in session storage with a 30-minute idle expiration.
   - Zero `localStorage` writes.
3. `ANALYTICS_ALLOWED`:
   - Uses `localStorage` to persist a pseudonymous `visitor_id` (`ap_vid`) with a 365-day expiration.
   - `is_returning` requires `first_seen` timestamp to be older than 30 minutes and within 365 days.
   - Explicit SDK configuration is authoritative: stale `localStorage` values cannot upgrade a restricted consent mode (`NO_STORAGE` or `ANONYMOUS`).

### 4.2 Prohibited Data & Privacy Filtering
- **Prohibited Identifiers:** Browser fingerprinting, canvas hashing, MAC addresses, device serials, IMEI, advertising IDs, and precise GPS coordinates are strictly forbidden.
- **Prohibited Payload Fields:** Recursive sanitization filters prohibited fields up to depth 5:
  - `email`, `phone`, `ssn`, `password`, `token`, `secret`, `credential`, `credit_card`, `chat_message`, `vin`, `gps`, `latitude`, `longitude`, `id_token`, `magic_link`.
- **Query Parameter Redaction:** URL paths and referrers automatically redact sensitive parameters (`token`, `auth`, `key`, `password`, `code`, `secret`, `ssn`, `email`, `session_id`).
- **Network Privacy:** Raw IP addresses are processed ephemerally in server memory for rate limiting and coarse country/region resolution, and are **never written to persistent storage**.

---

## 5. Session Lifecycle & Attribution

### 5.1 Atomic Session Persistence
Sessions are persisted in the `sessions` table with composite uniqueness:
- Unique Constraint: `(app_id, environment, session_id)`.
- Updates use atomic transactional upserts:
  ```sql
  INSERT INTO sessions (app_id, environment, session_id, visitor_id, started_at, last_activity, pageviews_count, entry_page, exit_page, is_bounce)
  VALUES (...)
  ON CONFLICT (app_id, environment, session_id) DO UPDATE SET
    last_activity = GREATEST(sessions.last_activity, EXCLUDED.last_activity),
    pageviews_count = sessions.pageviews_count + CASE WHEN :event_type = 'pageview' THEN 1 ELSE 0 END,
    exit_page = CASE WHEN EXCLUDED.last_activity >= sessions.last_activity THEN EXCLUDED.exit_page ELSE sessions.exit_page END,
    is_bounce = CASE WHEN (sessions.pageviews_count + CASE WHEN :event_type = 'pageview' THEN 1 ELSE 0 END) <= 1 THEN true ELSE false END;
  ```
- **Pageview Distinction:** Non-pageview custom events (e.g., clicks, engagement) update `last_activity` without incrementing `pageviews_count` or invalidating bounce metrics.
- **Idle Timeout:** Inactivity exceeding 30 minutes triggers session expiration, evaluated *before* the activity touch.

---

## 6. Database Privileges & Row-Level Security (RLS)

### 6.1 Database Roles
All runtime services operate with unprivileged PostgreSQL roles:
- `analytics_admin`: DDL migrations and schema changes. `NOBYPASSRLS`, `CREATEDB`, zero `SUPERUSER`.
- `analytics_ingest`: Ingestion collector service. `NOBYPASSRLS`, inserts events and idempotency records, updates sessions.
- `analytics_dashboard`: Dashboard service. `NOBYPASSRLS`, selects tenant events and metrics.
- `analytics_app`: General API application service. `NOBYPASSRLS`.

### 6.2 Tenant Isolation via RLS
- All data tables (`events`, all monthly partitions `events_y*`, `sessions`, `daily_page_metrics`, `daily_geo_metrics`, `ingestion_idempotency`) enforce:
  ```sql
  ALTER TABLE <table_name> ENABLE ROW LEVEL SECURITY;
  ALTER TABLE <table_name> FORCE ROW LEVEL SECURITY;
  ```
- Tenant scoping relies on transaction-local PostgreSQL session variables:
  - `app.current_app_id`
  - `app.current_environment`
- Isolation policies:
  - `tenant_isolation_policy`: Grants access where `app_id = current_setting('app.current_app_id') AND environment = current_setting('app.current_environment')`.
  - Ingestion insert policy enforces that inserted `app_id` and `environment` match the authenticated API session context.

---

## 7. Operational & Security Gates

- **Gate G0 (Architecture Decisions):** All core architectural choices recorded in ratified ADRs.
- **Gate G1 (Security Baseline):** Production rollout inside shared infrastructure blocked until project-level compute IAM least-privilege, private storage buckets, and Secret Manager injection are independently verified.
- **Gate G2 (Deployment Authorization):** Production deployment requires explicit user approval, documented runbooks, and defined rollback procedures.
- **Gate G3 (Consumer Integration):** Integration with consumer applications (AskAnna, GroundWorks/GCNav, Roomlyst, NutriLens) requires individual explicit milestone approval.
