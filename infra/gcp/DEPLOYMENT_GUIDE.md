# Google Cloud Deployment Guide — Analytics Platform

- **Target Project:** `leave-tracker-2025`
- **Target Region:** `us-central1`
- **Status:** **PLANNING ONLY (Deployment Prohibited During Milestone M2 / Blocked by Gate G1)**

---

## 1. Security Gate G1 Clearance Status (RELEASE BLOCKER)

> [!WARNING]
> **Production Deployment Blocker:** As documented in `docs/architecture/APPROVAL_DECISION_TABLE.md` and `docs/adr/ADR-001-cloud-project-and-isolation-boundary.md`, production deployment inside a shared project is strictly blocked until project-level baseline security requirements are verified or a dedicated isolated project (e.g., `enterprise-analytics-prod`) is formally authorized:
> 1. Compute services must operate under dedicated least-privilege service accounts (zero default compute service account with broad editor roles).
> 2. Storage buckets must enforce uniform bucket-level access with zero public exposure of application data or logs.
> 3. Secrets management must strictly enforce Cloud Secret Manager with zero hardcoded or fallback signing keys.
>
> This deployment guide provides the planned configuration required once Gate G1 clearance is formally granted by the platform owner.

---

## 2. Infrastructure Architecture & Connectivity

```
[ Browser / App Client ]
           │
           │ HTTPS (POST /v1/events)
           ▼
[ Google Cloud Run: analytics-api ]
  - Service Account: sa-analytics-api@leave-tracker-2025.iam.gserviceaccount.com
  - Autoscaling: min 0, max 10
  - DB Pool: min 2, max 5 per container
  - In-Memory Rate Limiting: 2,000 req/min/key, 120 req/min/IP
           │
           │ Cloud SQL Auth Proxy (Unix Domain Socket /cloudsql/...)
           ▼
[ Cloud SQL PostgreSQL 16: analytics-pg16 ]
  - Dedicated private database: analytics_db
  - Roles: analytics_admin, analytics_ingest, analytics_dashboard
  - RLS Enforcement: FORCE ROW LEVEL SECURITY on events and sessions
```

---

## 3. Deployment Steps (Runbook)

### Step 3.1: Service Account Provisioning
```bash
# 1. Create dedicated service account
gcloud iam service-accounts create sa-analytics-api \
  --project=leave-tracker-2025 \
  --display-name="Analytics Platform Cloud Run Service Account"

# 2. Grant least-privilege project roles
gcloud projects add-iam-policy-binding leave-tracker-2025 \
  --member="serviceAccount:sa-analytics-api@leave-tracker-2025.iam.gserviceaccount.com" \
  --role="roles/cloudsql.client"

gcloud projects add-iam-policy-binding leave-tracker-2025 \
  --member="serviceAccount:sa-analytics-api@leave-tracker-2025.iam.gserviceaccount.com" \
  --role="roles/monitoring.metricWriter"

gcloud projects add-iam-policy-binding leave-tracker-2025 \
  --member="serviceAccount:sa-analytics-api@leave-tracker-2025.iam.gserviceaccount.com" \
  --role="roles/logging.logWriter"
```

### Step 3.2: Secret Manager Secret Creation
```bash
# 1. Create database password secret
gcloud secrets create analytics-db-password \
  --project=leave-tracker-2025 \
  --replication-policy="automatic"

echo -n "<GENERATE_STRONG_RANDOM_PASSWORD>" | gcloud secrets versions add analytics-db-password --data-file=-

# 2. Create JWT signing secret
gcloud secrets create analytics-jwt-secret \
  --project=leave-tracker-2025 \
  --replication-policy="automatic"

echo -n "<GENERATE_SECURE_JWT_SECRET_MIN_32_CHARS>" | gcloud secrets versions add analytics-jwt-secret --data-file=-

# 3. Grant scoped secretAccessor permissions to sa-analytics-api
gcloud secrets add-iam-policy-binding analytics-db-password \
  --member="serviceAccount:sa-analytics-api@leave-tracker-2025.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding analytics-jwt-secret \
  --member="serviceAccount:sa-analytics-api@leave-tracker-2025.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### Step 3.3: Cloud SQL PostgreSQL 16 Provisioning
```bash
# Provision Cloud SQL instance with automated daily backups and point-in-time recovery
gcloud sql instances create analytics-pg16 \
  --project=leave-tracker-2025 \
  --database-version=POSTGRES_16 \
  --tier=db-custom-1-3840 \
  --region=us-central1 \
  --backup-start-time=03:00 \
  --enable-point-in-time-recovery \
  --retained-backups-count=7 \
  --storage-auto-increase \
  --storage-size=20GB

# Create application database
gcloud sql databases create analytics_db \
  --instance=analytics-pg16 \
  --project=leave-tracker-2025
```

### Step 3.4: Database Schema Initialization & Alembic Migrations
```bash
# Connect via Cloud SQL Auth Proxy on operator machine
cloud-sql-proxy leave-tracker-2025:us-central1:analytics-pg16 --port=5434

# 1. Apply init-production-db.sql with secure generated passwords (M2-15)
psql -h localhost -p 5434 -U postgres -d analytics_db \
  -v ON_ERROR_STOP=1 \
  -v admin_pass="'$ADMIN_DB_PASSWORD'" \
  -v ingest_pass="'$INGEST_DB_PASSWORD'" \
  -v dashboard_pass="'$DASHBOARD_DB_PASSWORD'" \
  -v app_pass="'$APP_DB_PASSWORD'" \
  -f infra/gcp/init-production-db.sql

# 2. Apply Alembic migrations
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5434
export POSTGRES_DB=analytics_db
export POSTGRES_USER=analytics_admin
export POSTGRES_PASSWORD="$ADMIN_DB_PASSWORD"
alembic -c api/alembic.ini upgrade head
```

### Step 3.5: Cloud Run Service Deployment
```bash
# Deploy service using declarative Knative manifest
gcloud run services replace infra/gcp/cloudrun-service.yaml \
  --project=leave-tracker-2025 \
  --region=us-central1
```

---

## 4. Monitoring & Alerting

Configure Cloud Monitoring alerts for `analytics-api`:
1. **HTTP 5xx Error Rate:** Alert when 5xx responses exceed 1% over a 5-minute rolling window.
2. **Container Restarts / Crashes:** Alert on unexpected container terminations.
3. **Database Connection Saturation:** Alert when Cloud SQL active connections exceed 80% of max capacity.
4. **Ingestion Latency:** Alert when p95 response time for `POST /v1/events` exceeds 500ms.

---

## 5. Rollback Procedure

If a deployed revision introduces defects, roll back traffic immediately:
```bash
# 1. List revisions
gcloud run revisions list \
  --service=analytics-api \
  --project=leave-tracker-2025 \
  --region=us-central1

# 2. Direct 100% of traffic to the previous healthy revision
gcloud run services update-traffic analytics-api \
  --project=leave-tracker-2025 \
  --region=us-central1 \
  --to-revisions=<PREVIOUS_HEALTHY_REVISION>=100
```
