# Analytics Platform — Architectural Decision & Approval Register

## 1. Overview of Unresolved Architectural Decisions

In accordance with Milestone M0 requirements and `IMPLEMENTATION_PLAN.md`, this register catalogs all core technical decisions, identifies open items, and establishes an approval framework for project stakeholders.

---

## 2. Decision & Approval Matrix

| Decision ID | Architectural Domain | Evaluated Options | Recommended Decision | Stakeholder Approval Status | Gate Reference |
|:---:|---|---|---|:---:|:---:|
| **DEC-01** | **GCP Project Boundary** | 1. Shared `leave-tracker-2025`<br>2. Dedicated `enterprise-analytics-prod` | **Dedicated Project (`enterprise-analytics-prod`)** for production. Shared project permitted for local/dev pre-production only. | **PENDING APPROVAL** | Gate G0 / Gate G1 |
| **DEC-02** | **PostgreSQL Hosting** | 1. Cloud SQL for PostgreSQL 16<br>2. External Serverless (Neon/Supabase)<br>3. Cloud Firestore (Rejected) | **Cloud SQL for PostgreSQL 16** via Cloud Run Cloud SQL Auth Proxy (Unix socket). Avoids VPC connector fee while maintaining data residency in GCP. | **PENDING APPROVAL** | Gate G0 / Gate G2 |
| **DEC-03** | **Production Release Gate** | 1. Deploy immediately to shared project<br>2. Block production until shared project security baselines are verified | **Production Release BLOCKED (Gate G1)** until project-level compute IAM least-privilege, private storage buckets, and secure secret injection are independently verified or a dedicated project is authorized. | **CONFIRMED MANDATORY** | Gate G1 |
| **DEC-04** | **Multi-Tenant Model** | 1. Schema-per-app (`askanna.*`)<br>2. Database-per-app<br>3. Shared tables with RLS | **Shared Tables with Composite Keys & PostgreSQL Row-Level Security (RLS)** (ADR-003). Eliminates migration sprawl while providing defense-in-depth isolation. | **RATIFIED (M0)** | Gate G0 |
| **DEC-05** | **Ingestion Durability** | 1. Direct durable DB writes<br>2. Cloud Pub/Sub queue<br>3. In-memory buffer (Rejected) | **Direct Transactionally Durable DB Writes** (ADR-004). No event acknowledged before disk commit. In-memory acknowledged buffers strictly banned. Pub/Sub deferred to Phase 2. | **RATIFIED (M0)** | Gate G0 |
| **DEC-06** | **Client Identification & Consent** | 1. Fingerprinting (Banned)<br>2. Third-party cookies (Rejected)<br>3. Three-Tier Consent Model | **Three-Tier Consent Model** (ADR-005): `NO_STORAGE`, `ANONYMOUS` (session-only), `ANALYTICS_ALLOWED` (first-party localStorage). Zero raw IP storage. URL parameter scrubbing. | **RATIFIED (M0)** | Gate G0 |
| **DEC-07** | **Ingestion Auth & Abuse** | 1. Origin checking as auth (Rejected)<br>2. Write-only scoped keys + origin abuse heuristic | **Write-Only Keys (`apk_live_...`, `apk_test_...`)** hashed with SHA-256 + CORS preflight & origin heuristic filter + per-IP rate limiting (ADR-006). | **RATIFIED (M0)** | Gate G0 |
| **DEC-08** | **Dashboard Auth & RBAC** | 1. Reuse existing consumer app auth (Rejected)<br>2. Independent OIDC / JWT + RBAC | **Independent OIDC / JWT + Platform RBAC** (`SuperAdmin`, `AppAdmin`, `AppViewer`) + immutable `audit_logs` for all data exports (ADR-007). | **RATIFIED (M0)** | Gate G0 |
| **DEC-09** | **Custom Ingestion Domains** | 1. Default `*.run.app` URLs<br>2. First-party subdomains (e.g. `telemetry.app.com`) | **First-Party Subdomains** via Cloud Run custom domain mapping (ADR-008) to minimize browser ad-blocker false positives. | **PENDING APPROVAL** | Gate G0 |
| **DEC-10** | **Data Lifecycle & Retention** | 1. Unbounded raw events<br>2. Row-by-row deletions<br>3. Partition drop + Rollups | **90-Day Raw Event Partition Pruning** (`DROP TABLE`) + **400-Day Pre-Aggregated Rollups** + GDPR Article 17 Erasure API (ADR-009). | **RATIFIED (M0)** | Gate G0 |
| **DEC-11** | **Client Application Integration** | 1. Blanket consumer app access<br>2. Isolated per-app authorization | **Separate Authorization Gate (Gate G3)** per app: AskAnna TEST, GroundWorks TEST (`gcnav2.com` only, zero `index.php`), Roomlyst, NutriLens. | **CONFIRMED MANDATORY** | Gate G3 |

---

## 3. Immediate Action Items for Stakeholder Review

1. **Review DEC-01 (GCP Project Boundary):**
   - Confirm whether a new GCP project (e.g. `enterprise-analytics-prod`) will be provisioned for production analytics, or if coexistence in `leave-tracker-2025` is preferred after security hardening.
2. **Review DEC-02 (PostgreSQL Provider):**
   - Confirm approval of Google Cloud SQL for PostgreSQL 16 via Cloud SQL Auth Proxy, or indicate if an external serverless PostgreSQL provider (Neon) is preferred for development staging.
3. **Review DEC-09 (Custom Domain Allocation):**
   - Identify designated first-party DNS subdomains for telemetry ingestion (e.g., `telemetry.askanna.ai`, `track.gcnav2.com`).
