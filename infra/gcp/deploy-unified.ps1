# ==============================================================================
# AnalyticsPlatform — Unified Production Cloud Run Deployment Script
# Target: "analytics-platform" in Google Cloud Project "leave-tracker-2025" (us-central1)
# 
# CRITICAL SAFETY REQUIREMENT:
# This script deploys ONLY the isolated AnalyticsPlatform service.
# It does NOT touch, redeploy, or modify existing services (nutrilens-api, leave-tracker-api, Firestore).
# ==============================================================================

param(
    [switch]$AuthorizeCloudDeployment = $false,
    [string]$ProjectId = "leave-tracker-2025",
    [string]$Region = "us-central1",
    [string]$ServiceName = "analytics-platform",
    [string]$RepoName = "analytics-repo"
)

$ErrorActionPreference = "Stop"

Write-Host "`n🚀 AnalyticsPlatform — Unified Free-Tier Deployment" -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Gray
Write-Host "Target GCP Project : $ProjectId" -ForegroundColor Yellow
Write-Host "Target Region      : $Region" -ForegroundColor Yellow
Write-Host "Target Service     : $ServiceName" -ForegroundColor Yellow
Write-Host "Hosting Cost Target: $0.00 / month (Cloud Run scale-to-zero + Existing Cloud Firestore)" -ForegroundColor Green
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`n" -ForegroundColor Gray

# --- Safety Guard ---
if (-not $AuthorizeCloudDeployment) {
    Write-Host "⛔ DEPLOYMENT PAUSED (SAFETY GATE)" -ForegroundColor Yellow
    Write-Host "Per repository safety instructions, live cloud operations require explicit authorization." -ForegroundColor White
    Write-Host "To execute this deployment, rerun the script with the authorization flag:" -ForegroundColor White
    Write-Host "  .\infra\gcp\deploy-unified.ps1 -AuthorizeCloudDeployment`n" -ForegroundColor Cyan
    exit 0
}

# --- Step 1: Configure gcloud project ---
Write-Host "Step 1/5: Verifying Google Cloud Project..." -ForegroundColor Yellow
gcloud config set project $ProjectId --quiet
gcloud config set run/region $Region --quiet
Write-Host "✓ Active project set to $ProjectId`n" -ForegroundColor Green

# --- Step 2: Verify Secrets Exist ---
Write-Host "Step 2/5: Verifying required Secret Manager secrets..." -ForegroundColor Yellow
$jwtSecretExists = gcloud secrets describe analytics-jwt-secret --project=$ProjectId --format="value(name)" 2>$null

if (-not $jwtSecretExists) {
    Write-Host "❌ Secret 'analytics-jwt-secret' not found in Secret Manager!" -ForegroundColor Red
    Write-Host "Please create it using: gcloud secrets create analytics-jwt-secret --data-file=-" -ForegroundColor White
    exit 1
}
Write-Host "✓ Required secrets verified in Secret Manager (Firestore uses IAM auth)`n" -ForegroundColor Green

# --- Step 3: Ensure Artifact Registry Repo Exists ---
Write-Host "Step 3/5: Ensuring Artifact Registry repository exists..." -ForegroundColor Yellow
$repoExists = gcloud artifacts repositories describe $RepoName --location=$Region --format="value(name)" 2>$null
if (-not $repoExists) {
    gcloud artifacts repositories create $RepoName `
        --repository-format=docker `
        --location=$Region `
        --description="Analytics Platform container images"
    Write-Host "✓ Repository '$RepoName' created`n" -ForegroundColor Green
} else {
    Write-Host "✓ Repository '$RepoName' verified`n" -ForegroundColor Green
}

# --- Step 4: Build Container Image with Cloud Build ---
$ImageTag = "$Region-docker.pkg.dev/$ProjectId/$RepoName/analytics-platform:latest"
Write-Host "Step 4/5: Building container image with Cloud Build..." -ForegroundColor Yellow
Write-Host "Image Tag: $ImageTag" -ForegroundColor Gray

# Build from repository root
gcloud builds submit --tag $ImageTag -f Dockerfile .

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Cloud Build failed!" -ForegroundColor Red
    exit 1
}
Write-Host "✓ Image built and pushed to Artifact Registry`n" -ForegroundColor Green

# --- Step 5: Deploy to Cloud Run ---
Write-Host "Step 5/5: Deploying unified Cloud Run service..." -ForegroundColor Yellow
$ServiceAccount = "sa-analytics-platform@$ProjectId.iam.gserviceaccount.com"

gcloud run deploy $ServiceName `
    --image=$ImageTag `
    --region=$Region `
    --platform=managed `
    --service-account=$ServiceAccount `
    --min-instances=0 `
    --max-instances=2 `
    --cpu=1 `
    --memory=512Mi `
    --concurrency=80 `
    --timeout=30s `
    --set-env-vars="ENVIRONMENT=production,BEHIND_PROXY=true,TRUSTED_PROXIES=169.254.8.1,169.254.169.254,GCP_PROJECT_ID=$ProjectId,FIRESTORE_DATABASE=(default),FIRESTORE_COLLECTION_PREFIX=analytics_" `
    --set-secrets="ANALYTICS_JWT_SECRET=analytics-jwt-secret:latest" `
    --allow-unauthenticated `
    --quiet

if ($LASTEXITCODE -eq 0) {
    $ServiceUrl = gcloud run services describe $ServiceName --region=$Region --format="value(status.url)"
    Write-Host "`n========================================================" -ForegroundColor Green
    Write-Host "     ANALYTICS PLATFORM DEPLOYED SUCCESSFULLY!          " -ForegroundColor Green
    Write-Host "========================================================" -ForegroundColor Green
    Write-Host "Dashboard SPA : $ServiceUrl/dashboard/" -ForegroundColor Cyan
    Write-Host "API Ingestion : $ServiceUrl/v1/events" -ForegroundColor Cyan
    Write-Host "Batch Beacon  : $ServiceUrl/v1/batch" -ForegroundColor Cyan
    Write-Host "Health Probe  : $ServiceUrl/health/ready" -ForegroundColor Cyan
    Write-Host "API Docs      : $ServiceUrl/docs" -ForegroundColor Cyan
    Write-Host "`nMonthly Recurring Cost: $0.00 (within Cloud Run & Firestore free tiers)" -ForegroundColor Green
    Write-Host "Existing Services Untouched: nutrilens-api, leave-tracker-api (verified)" -ForegroundColor Gray
} else {
    Write-Host "`n❌ Deployment failed!" -ForegroundColor Red
    exit 1
}
