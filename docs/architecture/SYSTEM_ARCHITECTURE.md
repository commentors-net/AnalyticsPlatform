# Analytics Platform — System Architecture Specification

## 1. Executive Overview

The **Self-Hosted Multi-Application Analytics Platform** is an independent, privacy-first telemetry and product intelligence platform. It is designed to capture, persist, aggregate, and visualize user interactions, operational events, and system telemetry across multiple client applications:

- **AskAnna:** AI assistant and customer intelligence conversational workflows.
- **GroundWorks:** Real estate analysis, civil engineering, and GCNav workflows.
- **Roomlyst:** Interior design, 3D room styling, and space modeling workflows.
- **NutriLens:** Food nutrition logging, meal analysis, and mobile telemetry (pending separate authorization).
- **Future Applications:** Seamless onboarding via tenant registry.

### Core Architecture Tenets:
1. **Strict Multi-Tenant Isolation:** Complete data, credential, and query segregation across applications and between `test` and `live` environments.
2. **Durable Ingestion:** An event is never acknowledged to a client (HTTP 200/202) before it is committed to durable storage. In-memory-only acknowledged buffers are prohibited.
3. **Fail-Open Client SDKs:** Analytics tracking failures must never disrupt host application functionality or degrade end-user experience.
4. **Privacy-by-Design:** No device fingerprinting; no collection of PII, VINs, or secret query parameters; zero raw IP persistence; transparent 3-tier consent enforcement with built-in `NO_STORAGE` mode.
5. **Operational Autonomy:** Independent source code, deployment pipelines, databases, and IAM credentials completely separate from NutriLens and Leave Tracker.

---

## 2. End-to-End System Topology

```mermaid
flowchart TD
    subgraph ClientLayer["Untrusted Client Applications"]
        direction TB
        subgraph WebClients["Web Applications"]
            AA_Web["AskAnna Web SPA\n(Browser SDK)"]
            GW_Web["GroundWorks Web\n(Browser SDK)"]
            RL_Web["Roomlyst Web\n(Browser SDK)"]
        end
        subgraph ServerClients["Backend Server Applications"]
            AA_Srv["AskAnna Backend\n(Python SDK)"]
            GW_Srv["GroundWorks API\n(Python SDK)"]
        end
    end

    subgraph EdgeRouting["Edge & Domain Layer"]
        Domain["First-Party Telemetry Domains\n- telemetry.askanna.ai\n- track.gcnav2.com\n- events.roomlyst.com\n(Google-managed TLS / Cloud Run Mapping)"]
    end

    subgraph GCPAnalytics["Analytics Platform Infrastructure (Cloud Run & Cloud SQL)"]
        subgraph IngestionService["Public Ingestion Tier (Cloud Run)"]
            IngestAPI["analytics-ingest-api\n- FastAPI + Uvicorn (Port 8080)\n- Scaled Min: 0, Max: 20\n- Concurrency: 80 per instance\n- Dedicated SA: sa-analytics-ingest\n- In-Memory GeoIP Lookup & PII Sanitizer\n- Zero Raw IP Persistence"]
        end

        subgraph DatabaseTier["Relational Storage Tier (PostgreSQL 16)"]
            Postgres[("Google Cloud SQL: PostgreSQL 16\n- High Availability / Automated Daily Backups\n- PITR 7-Day Journaling\n- Monthly Partitioned 'events' Table\n- Row-Level Security (RLS) Enforced\n- Pre-aggregated Daily Rollups")]
        end

        subgraph ManagementService["Administrative Tier (Cloud Run)"]
            DashAPI["analytics-dashboard\n- FastAPI Backend + React 19 SPA\n- Scaled Min: 0, Max: 5\n- Dedicated SA: sa-analytics-dashboard\n- OIDC / JWT Authentication\n- Platform RBAC & Scoped Query Engine\n- Immutable Audit Logging"]
        end

        subgraph SecretStore["Google Secret Manager"]
            Secrets["Managed Secrets:\n- analytics-db-credentials\n- analytics-jwt-secret\n- analytics-write-key-salt"]
        end
    end

    subgraph AdminUsers["Administrative Users"]
        Operator["Platform SuperAdmin\n& Tenant AppAdmins\n(Browser / OIDC Auth)"]
    end

    WebClients -->|HTTPS POST /v1/events\n(write_key)| Domain
    ServerClients -->|HTTPS POST /v1/batch\n(write_key)| Domain
    Domain --> IngestAPI
    
    IngestAPI -->|Direct Transactional Commit\n(Unix Socket / Cloud SQL Proxy)| Postgres
    IngestAPI -.->|Read Secrets at Startup| Secrets

    Operator -->|HTTPS / Dashboard SPA| DashAPI
    DashAPI -->|Scoped Queries / RLS\n(Unix Socket / Cloud SQL Proxy)| Postgres
    DashAPI -.->|Read Secrets at Startup| Secrets
```

---

## 3. Component Deep Dive

### 3.1 Public Ingestion Service (`analytics-ingest-api`)
- **Runtime:** Python 3.11+, FastAPI, Uvicorn, Pydantic v2, `asyncpg`.
- **Ingress:** Public HTTPS (`--allow-unauthenticated`).
- **Identity & Least Privilege:**
  - Runs under dedicated service account: `sa-analytics-ingest@<PROJECT_ID>.iam.gserviceaccount.com`.
  - Roles granted: `roles/cloudsql.client`, `roles/secretmanager.secretAccessor` (scoped only to database credentials).
  - Strictly **NO** access to NutriLens Firestore, Cloud Storage buckets, or Compute Admin.
- **Concurrency & Autoscaling:**
  - Container concurrency: 80 requests per container.
  - Autoscaling: Min 0, Max 20 containers.
  - Bounded connection pool per container: Min 2, Max 10 connections. Total DB connections capped at 200 during maximum peak surge.
- **Pipeline Responsibilities:**
  1. Authenticates `write_key` via SHA-256 hash lookup in cache/database.
  2. Enforces CORS preflight (`OPTIONS`) and inspects `Origin` allowlists as an abuse check.
  3. Enforces rate limits per IP and per `write_key`.
  4. Resolves IP to Coarse GeoIP (Country, Region, City) in volatile RAM using offline database.
  5. Masks IPv4 to `/24` or drops IP entirely; strips sensitive query parameters from URLs.
  6. Rejects payloads containing prohibited fields (VIN, chat messages, credit cards, PII).
  7. Inserts events into PostgreSQL within a committed transaction before returning HTTP `201 Created` or `202 Accepted`.

### 3.2 Storage Engine (PostgreSQL 16)
- **Engine:** PostgreSQL 16 (Google Cloud SQL for PostgreSQL).
- **Storage Configuration:** SSD persistent disk with automatic storage increase enabled.
- **Disaster Recovery:**
  - Daily automated backups with 30-day retention.
  - Point-in-Time Recovery (PITR) enabled with 7-day transaction log retention.
- **Data Organization:**
  - **Partitioned Raw Events:** Partitioned by month on `timestamp` (`events_y2026m11`, etc.).
  - **Composite Keys:** Every row contains `(id, app_id, environment, timestamp)`.
  - **Row-Level Security (RLS):** Database-level security policies prevent queries from returning records belonging to another tenant or environment.
  - **Aggregated Rollup Tables:** Daily metrics rollups computed nightly, retained for 400 days without individual visitor IDs.

### 3.3 Administrative Dashboard Service (`analytics-dashboard`)
- **Runtime:** React 19 SPA served via Vite, backed by FastAPI administrative API routes.
- **Ingress:** Public HTTPS, protected by server-side authentication.
- **Identity & Least Privilege:**
  - Runs under dedicated service account: `sa-analytics-dashboard@<PROJECT_ID>.iam.gserviceaccount.com`.
  - Roles granted: `roles/cloudsql.client`, `roles/secretmanager.secretAccessor`.
- **Security & Authorization:**
  - OIDC / JWT authentication (15-minute access token lifespan, HttpOnly secure cookies).
  - Role-Based Access Control (RBAC): `SuperAdmin`, `AppAdmin`, `AppViewer`.
  - Mandatory environment scoping: queries must specify `env=test` or `env=live`.
  - Immutable audit logging: every export and key rotation is persisted to `audit_logs`.

---

## 4. Google Cloud Hosting & Deployment Boundaries

### 4.1 Coexistence Evaluation vs. Dedicated Project

| Dimension | Coexistence in Shared Project | Dedicated Project `enterprise-analytics-prod` |
|---|---|---|
| **Resource Isolation** | Shared GCP project boundary | Absolute project-level isolation |
| **IAM Blast Radius** | High risk if co-hosted services hold broad roles | Zero cross-system blast radius |
| **Cost Transparency** | Blended billing requiring label filtering | 100% direct billing attribution |
| **Release Gate Status** | **BLOCKED** by Gate G1 until project baselines verified | **CLEARED** (independent greenfield deployment) |
| **Recommendation** | Permitted for non-production M1–M4 dev/staging | **Primary recommendation for production launch** |

### 4.2 Network Connectivity: Cloud SQL Auth Proxy vs. Serverless VPC Access
- To avoid the ongoing fixed cost of a Serverless VPC Access Connector (~$15/month for e2-micro connectors), Cloud Run services connect to Cloud SQL using the native **Cloud SQL Auth Proxy** over Unix domain sockets (`/cloudsql/<INSTANCE_CONNECTION_NAME>`).
- This configuration ensures end-to-end mTLS encryption, automated IAM credential rotation, and eliminates public exposure of PostgreSQL database ports without incurring VPC connector fees.

### 4.3 Production Release Blockers (Gate G1)
Coexistence in a shared GCP project is strictly conditional. The following baseline prerequisites are **release blockers** before any shared-project production deployment:
1. All compute services must run under dedicated least-privilege service accounts (zero default compute service account with broad editor roles).
2. Uniform bucket-level access and zero public bucket exposure of application data or logs.
3. Secret Manager injection enforced with zero hardcoded or fallback keys in code.
2. Public read exposure of user meal photos and application logs in `gs://leave-tracker-2025-frontend`.
3. Hardcoded fallback `SECRET_KEY` in `backend/app/leave_tracker/core/security.py`.
4. Disabled PITR and backup schedules on Firestore.

*Boundary Rule: These vulnerabilities must be resolved in the NutriLens repository by its owners; no remediation code will be committed within the AnalyticsPlatform repository.*
