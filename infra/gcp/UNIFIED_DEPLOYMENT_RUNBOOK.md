# AnalyticsPlatform — Unified Deployment & Free-Tier Runbook (Firestore-Backed)

**Target GCP Project:** `leave-tracker-2025`  
**Target Region:** `us-central1`  
**Service Name:** `analytics-platform`  
**Target Recurring Cost:** **$0.00 / month**  
**Safety Gate:** Planning & Preparation only. **DO NOT EXECUTE WITHOUT USER AUTHORIZATION.**

---

## 1. Architectural Principles & Safety Boundary

### A. Strict Zero-Impact Isolation Boundary
- **Existing Deployments Untouched:** `nutrilens-api`, `leave-tracker-api`, existing Firestore collections (`users`, `people`, `types`, `absences`, `nutrilens_*`, `ai_instructions`), Cloud Storage buckets, and DNS mappings remain completely untouched and unmodified.
- **Dedicated Identity:** Operates strictly under `sa-analytics-platform@leave-tracker-2025.iam.gserviceaccount.com`.
- **Dedicated Data Namespace:** Uses the existing project `leave-tracker-2025` Cloud Firestore database `(default)`, isolated strictly under the dedicated `analytics_*` collection prefix and subcollections:
  - `analytics_users`
  - `analytics_apps`
  - `analytics_api_keys`
  - `analytics_idempotency`
  - `analytics_audit_logs`
  - `analytics_data/{app_id}_{environment}/events`
  - `analytics_data/{app_id}_{environment}/sessions`
- **Zero Sibling Application Collisions:** Zero query, read, or write overlap with sibling applications sharing the project.

### B. Single Installation with Dual LIVE & TEST Support
- **No Duplicate Staging Services:** Eliminates duplicate `test` and `live` Cloud Run services. Both LIVE and TEST telemetry are ingested and served by the single `analytics-platform` service.
- **Environment Isolation:**
  - Ingestion keys starting with `apk_live_` write to `analytics_data/{app_id}_live/events`.
  - Ingestion keys starting with `apk_test_` write to `analytics_data/{app_id}_test/events`.
  - Subcollection namespaces enforce physical data separation without requiring complex database partitioning or index maintenance.
  - The interactive Administrative Dashboard SPA at `/dashboard/` includes an **Environment Switcher** allowing instant toggling between LIVE metrics and isolated TEST sandbox data.

### C. True $0/Month Free-Tier Cost Model
- **Cloud Run (Scale to Zero):** Configured with `minScale: 0` and `maxScale: 2`. Consumes 0 vCPU and 0 memory when idle. Fits completely within the GCP perpetual free tier of 2,000,000 requests/month and 360,000 vCPU-seconds/month.
- **Google Cloud Firestore (Existing (default)):** Fits within GCP Free Tier (1 GiB stored data, 50,000 document reads/day, 20,000 document writes/day). Incurs $0.00/month recurring cost. Eliminates external PostgreSQL/Neon infrastructure completely.

---

## 2. Pre-Deployment Prerequisites

Ensure your terminal has `gcloud` authenticated with permissions on `leave-tracker-2025`:
```bash
gcloud config set project leave-tracker-2025
gcloud config set run/region us-central1
```

Required IAM Roles for Deployment Administrator:
- `roles/run.admin`
- `roles/iam.serviceAccountAdmin`
- `roles/secretmanager.admin`
- `roles/artifactregistry.admin`
- `roles/cloudbuild.builds.editor`

---

## 3. Step-by-Step Provisioning Guide

### Step 3.1: Configure Cloud Firestore IAM Access

The Cloud Run service account requires `roles/datastore.user` to access Firestore in `leave-tracker-2025`:
```bash
gcloud projects add-iam-policy-binding leave-tracker-2025 \
  --member="serviceAccount:sa-analytics-platform@leave-tracker-2025.iam.gserviceaccount.com" \
  --role="roles/datastore.user"
```

*Reaffirmed Prohibited Roles for sa-analytics-platform:*
- `roles/editor`
- `roles/owner`
- `roles/storage.admin`
- `roles/iam.securityAdmin`

---

### Step 3.2: Store Production Secrets in Secret Manager

Firestore authentication is handled transparently via Google Cloud IAM (Application Default Credentials). Only the administrative JWT secret is stored in Secret Manager:

```bash
# 1. Generate strong 64-character JWT secret
JWT_SECRET=$(openssl rand -hex 32)
echo -n "$JWT_SECRET" | gcloud secrets create analytics-jwt-secret \
  --replication-policy="automatic" \
  --data-file=- \
  --project=leave-tracker-2025

# 2. Grant Secret Accessor to the service account
gcloud secrets add-iam-policy-binding analytics-jwt-secret \
  --member="serviceAccount:sa-analytics-platform@leave-tracker-2025.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor" \
  --project=leave-tracker-2025
```

---

### Step 3.3: Build Container Image with Cloud Build

```bash
# 1. Verify Artifact Registry repository exists
gcloud artifacts repositories create analytics-repo \
  --repository-format=docker \
  --location=us-central1 \
  --description="Analytics Platform container repository"

# 2. Build image from repository root
gcloud builds submit --tag us-central1-docker.pkg.dev/leave-tracker-2025/analytics-repo/analytics-platform:latest .
```

---

### Step 3.4: Deploy to Cloud Run

Run the unified deployment script (requires explicit user authorization):
```powershell
.\infra\gcp\deploy-unified.ps1 -AuthorizeCloudDeployment
```

Or deploy directly via `gcloud`:
```bash
gcloud run deploy analytics-platform \
  --image=us-central1-docker.pkg.dev/leave-tracker-2025/analytics-repo/analytics-platform:latest \
  --region=us-central1 \
  --platform=managed \
  --service-account=sa-analytics-platform@leave-tracker-2025.iam.gserviceaccount.com \
  --min-instances=0 \
  --max-instances=2 \
  --cpu=1 \
  --memory=512Mi \
  --concurrency=80 \
  --timeout=30s \
  --set-env-vars="ENVIRONMENT=production,BEHIND_PROXY=true,TRUSTED_PROXIES=169.254.8.1,169.254.169.254,GCP_PROJECT_ID=leave-tracker-2025,FIRESTORE_DATABASE=(default),FIRESTORE_COLLECTION_PREFIX=analytics_" \
  --set-secrets="ANALYTICS_JWT_SECRET=analytics-jwt-secret:latest" \
  --allow-unauthenticated
```

---

## 4. Post-Deployment Verification

Retrieve the live service URL:
```bash
SERVICE_URL=$(gcloud run services describe analytics-platform --region=us-central1 --format='value(status.url)')
echo "Deployed Service URL: $SERVICE_URL"
```

1. **Verify Health Endpoints:**
   ```bash
   curl -f "$SERVICE_URL/health/live"
   # Expected: {"status":"ok"}

   curl -f "$SERVICE_URL/health/ready"
   # Expected: {"status":"ready","database":"connected"}
   ```

2. **Verify Dashboard SPA:**
   Open `$SERVICE_URL/dashboard/` in a web browser. Confirm the login interface loads and the LIVE/TEST toggle functions.

3. **Run Automated End-to-End Smoke Test:**
   ```bash
   python scripts/smoke_test.py --endpoint="$SERVICE_URL"
   ```
   *Verifies all 11 architectural requirements against the live Cloud Run deployment.*

---

## 5. Rollback & Maintenance Procedures

### Instant Version Rollback
If a newly deployed image exhibits defects, roll traffic back immediately:
```bash
gcloud run services update-traffic analytics-platform \
  --region=us-central1 \
  --to-revisions=PREVIOUS_REVISION_NAME=100
```

### Scheduled Retention Maintenance
Prunes raw telemetry older than 90 days in Firestore:
```bash
python scripts/cleanup_retention.py --retention-days=90
```

---

## 6. Comprehensive Cost & Quota Analysis

| Service / Resource | Free Tier Allowance | Anticipated Monthly Usage | Projected Cost |
| :--- | :--- | :--- | :--- |
| **Cloud Run Invocations** | 2,000,000 requests / month | ~50,000 requests / month | **$0.00** |
| **Cloud Run Compute** | 360,000 vCPU-seconds / month | ~8,000 vCPU-seconds / month | **$0.00** |
| **Cloud Run Memory** | 180,000 GiB-seconds / month | ~4,000 GiB-seconds / month | **$0.00** |
| **Artifact Registry** | 500 MB storage free | ~110 MB image storage | **$0.00** |
| **Secret Manager** | 6 active secret versions free | 1 active secret | **$0.00** |
| **Google Cloud Firestore** | 1 GiB storage, 50k reads/day, 20k writes/day | ~20–50 MB, ~2,000 writes/day | **$0.00** |
| **Total Estimated Cost**| | | **$0.00 / month** |


### Potential Charge Triggers & Safety Caps:
1. **Cloud Run Max Instances:** Hard-capped at `maxScale: 2` to prevent billing runaway during DDoS or bot traffic.
2. **Neon Storage Limit:** Neon free tier provides 500 MB. The automated 90-day event retention pruning in `infra/prune-retention.sql` prevents data growth from ever exceeding 500 MB under expected traffic.
3. **Artifact Registry Old Images:** If multiple builds accumulate over 500 MB, clean up untagged old images via `gcloud artifacts docker images delete`.
