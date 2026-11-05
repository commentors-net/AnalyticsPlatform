# Google Cloud TEST Deployment Runbook — Analytics Platform

**Target Project:** `leave-tracker-2025`  
**Target Region:** `us-central1`  
**Target Environment:** `test` (Dedicated Sandbox)  
**Safety Gate:** Planning & Preparation only. **DO NOT EXECUTE WITHOUT USER AUTHORIZATION.**

---

## 1. Architectural & Isolation Boundaries

- **Zero Sibling Contamination:** The Analytics Platform TEST deployment does not touch, read, or modify any existing services, Firestore collections, buckets, or databases of `leave-tracker-2025` or sibling apps.
- **Dedicated Service Accounts:** Runs strictly under `sa-analytics-api-test` and `sa-analytics-dash-test`.
- **Dedicated Cloud SQL & Roles:** Operates under dedicated non-superuser role `analytics_app` with Row-Level Security enforced.
- **Fail-Open & Scale-to-Zero:** All Cloud Run services are configured with `minScale: 0` to minimize idle costs.

---

## 2. Pre-Deployment Prerequisites

Ensure your local or CI session has Google Cloud SDK installed and authenticated:
```bash
gcloud config set project leave-tracker-2025
gcloud auth list
```

Required IAM permissions on project `leave-tracker-2025`:
- `roles/run.admin`
- `roles/iam.serviceAccountAdmin`
- `roles/secretmanager.admin`
- `roles/cloudsql.admin`
- `roles/artifactregistry.admin`

---

## 3. Step-by-Step Deployment Procedure

### Step 3.1: Create Dedicated Service Accounts

```bash
# 1. API Test Service Account
gcloud iam service-accounts create sa-analytics-api-test \
  --display-name="Analytics API Test Service Identity"

# 2. Dashboard Test Service Account
gcloud iam service-accounts create sa-analytics-dash-test \
  --display-name="Analytics Dashboard Test Service Identity"

# 3. Grant Secret Manager Access to API Service Account
gcloud projects add-iam-policy-binding leave-tracker-2025 \
  --member="serviceAccount:sa-analytics-api-test@leave-tracker-2025.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

# 4. Grant Cloud SQL Client Access to API Service Account
gcloud projects add-iam-policy-binding leave-tracker-2025 \
  --member="serviceAccount:sa-analytics-api-test@leave-tracker-2025.iam.gserviceaccount.com" \
  --role="roles/cloudsql.client"
```

---

### Step 3.2: Provision Secret Manager Secrets

```bash
# Generate high-entropy secrets locally
JWT_TEST_SECRET=$(openssl rand -hex 32)
APP_DB_PASSWORD=$(openssl rand -hex 16)
ADMIN_DB_PASSWORD=$(openssl rand -hex 16)

# Create and populate secrets in Google Secret Manager
gcloud secrets create analytics-test-jwt-secret --replication-policy="automatic"
echo -n "$JWT_TEST_SECRET" | gcloud secrets versions add analytics-test-jwt-secret --data-file=-

gcloud secrets create analytics-test-db-app-password --replication-policy="automatic"
echo -n "$APP_DB_PASSWORD" | gcloud secrets versions add analytics-test-db-app-password --data-file=-

gcloud secrets create analytics-test-db-admin-password --replication-policy="automatic"
echo -n "$ADMIN_DB_PASSWORD" | gcloud secrets versions add analytics-test-db-admin-password --data-file=-
```

---

### Step 3.3: Provision Cloud SQL Test Instance

```bash
# Create cost-optimized micro instance (scale-to-zero friendly)
gcloud sql instances create analytics-pg16-test \
  --database-version=POSTGRES_16 \
  --tier=db-f1-micro \
  --region=us-central1 \
  --storage-type=SSD \
  --storage-size=10GB \
  --storage-auto-increase \
  --backup-start-time=03:00 \
  --database-flags=cloudsql.enable_pgaudit=on

# Create database
gcloud sql databases create analytics_test_db --instance=analytics-pg16-test
```

---

### Step 3.4: Initialize Schema and Database Roles

Execute the hardened database role and partition script:
```bash
# Connect via cloud-sql-proxy or Cloud Shell and run init script:
psql "host=127.0.0.1 port=5432 dbname=analytics_test_db user=postgres" \
  -v app_pwd="'$APP_DB_PASSWORD'" \
  -v admin_pwd="'$ADMIN_DB_PASSWORD'" \
  -f infra/gcp/init-production-db.sql

# Run Alembic migrations up to head:
POSTGRES_HOST=127.0.0.1 \
POSTGRES_PORT=5432 \
POSTGRES_DB=analytics_test_db \
POSTGRES_USER=analytics_admin \
POSTGRES_PASSWORD=$ADMIN_DB_PASSWORD \
python -m alembic -c api/alembic.ini upgrade head
```

---

### Step 3.5: Build & Push Container Images to Artifact Registry

```bash
# Ensure repository exists
gcloud artifacts repositories create analytics-repo \
  --repository-format=docker \
  --location=us-central1 \
  --description="Analytics Platform Container Images"

# Authenticate docker
gcloud auth configure-docker us-central1-docker.pkg.dev

# Build & Push API image
docker build -t us-central1-docker.pkg.dev/leave-tracker-2025/analytics-repo/analytics-api-test:latest -f Dockerfile .
docker push us-central1-docker.pkg.dev/leave-tracker-2025/analytics-repo/analytics-api-test:latest

# Build & Push Dashboard SPA image
docker build -t us-central1-docker.pkg.dev/leave-tracker-2025/analytics-repo/analytics-dashboard-test:latest -f dashboard/Dockerfile .
docker push us-central1-docker.pkg.dev/leave-tracker-2025/analytics-repo/analytics-dashboard-test:latest
```

---

### Step 3.6: Deploy Cloud Run Services

```bash
# Deploy API Service
gcloud run services replace infra/gcp/cloudrun-api-test.yaml --region=us-central1

# Deploy Dashboard SPA Service
gcloud run services replace infra/gcp/cloudrun-dashboard-test.yaml --region=us-central1

# Allow public unauthenticated ingestion and dashboard login
gcloud run services add-iam-policy-binding analytics-api-test \
  --region=us-central1 \
  --member="allUsers" \
  --role="roles/run.invoker"

gcloud run services add-iam-policy-binding analytics-dash-test \
  --region=us-central1 \
  --member="allUsers" \
  --role="roles/run.invoker"
```

---

## 4. Post-Deployment Smoke Verification

```bash
API_URL=$(gcloud run services describe analytics-api-test --region=us-central1 --format='value(status.url)')
DASH_URL=$(gcloud run services describe analytics-dash-test --region=us-central1 --format='value(status.url)')

# 1. Health Liveness & Readiness Checks
curl -f "$API_URL/health/live"
curl -f "$API_URL/health/ready"

# 2. Verify Dashboard Availability
curl -I "$DASH_URL/dashboard/"

# 3. Execute Smoke Test Suite against Live Test URL
python scripts/smoke_test.py --endpoint="$API_URL"
```

---

## 5. Rollback & Teardown Procedures

### Instant Rollback:
If an issue occurs after revision deployment, rollback to the prior known good revision:
```bash
gcloud run services update-traffic analytics-api-test \
  --region=us-central1 \
  --to-revisions=PREVIOUS_REVISION=100
```

### Complete Test Environment Teardown:
To completely remove all test resources and cease all billing:
```bash
gcloud run services delete analytics-api-test --region=us-central1 --quiet
gcloud run services delete analytics-dash-test --region=us-central1 --quiet
gcloud sql instances delete analytics-pg16-test --quiet
gcloud secrets delete analytics-test-jwt-secret --quiet
gcloud secrets delete analytics-test-db-app-password --quiet
gcloud secrets delete analytics-test-db-admin-password --quiet
gcloud iam service-accounts delete sa-analytics-api-test@leave-tracker-2025.iam.gserviceaccount.com --quiet
gcloud iam service-accounts delete sa-analytics-dash-test@leave-tracker-2025.iam.gserviceaccount.com --quiet
```

---

## 6. Incremental Cloud Cost Analysis

| Component | Sizing & Configuration | Estimated Monthly Cost |
| :--- | :--- | :--- |
| **Cloud SQL (Test)** | `db-f1-micro` (0.6 GB RAM, 10 GB SSD) | ~$12.00 – $18.00 / month |
| **Cloud Run (API Test)** | Scale-to-zero (0 min, 3 max), 512 MB | ~$0.00 – $3.00 / month |
| **Cloud Run (Dashboard Test)** | Scale-to-zero (0 min, 2 max), 256 MB | ~$0.00 – $2.00 / month |
| **Secret Manager** | 3 secrets, minimal version calls | < $0.20 / month |
| **Cloud Storage / Artifacts**| Container images (~200 MB) | < $0.50 / month |
| **Total Estimated Incremental Cost** | | **~$15.00 – $25.00 / month** |
