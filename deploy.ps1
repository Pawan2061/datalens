# ============================================================================
# DataLens Analytics — Google Cloud Run Deployment Script (Windows PowerShell)
# ============================================================================
#
# Prerequisites:
#   1. Install gcloud CLI: https://cloud.google.com/sdk/docs/install
#   2. Authenticate: gcloud auth login
#   3. Copy backend\.env.example → backend\.env and fill in your secrets
#   4. Copy frontend\.env.example → frontend\.env and fill in your values
#
# Usage:
#   .\deploy.ps1
# ============================================================================
$ErrorActionPreference = "Stop"

# ── Configuration (edit or set env vars) ──────────────────────────────
$PROJECT_ID = if ($env:GCP_PROJECT_ID) { $env:GCP_PROJECT_ID } else { "your-gcp-project-id" }
$REGION     = if ($env:GCP_REGION)     { $env:GCP_REGION }     else { "asia-south1" }
$BACKEND_SERVICE  = "datalens-api"
$FRONTEND_SERVICE = "datalens-app"

Write-Host "`n=== DataLens Deployment ===" -ForegroundColor Cyan
Write-Host "  Project: $PROJECT_ID"
Write-Host "  Region:  $REGION"

# Validate that .env exists
if (-not (Test-Path "backend\.env")) {
    Write-Host "ERROR: backend\.env not found. Copy backend\.env.example and fill in your secrets." -ForegroundColor Red
    exit 1
}

gcloud config set project $PROJECT_ID

# ── Step 1: Generate env-vars YAML from .env ──────────────────────────
Write-Host "`n=== Generating deployment env vars ===" -ForegroundColor Cyan
python3 -c @"
import json
env = {}
with open('backend/.env') as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, _, val = line.partition('=')
        env[key.strip()] = val.strip()
if 'CORS_ORIGINS' in env:
    try:
        json.loads(env['CORS_ORIGINS'])
    except json.JSONDecodeError:
        env['CORS_ORIGINS'] = '[\"*\"]'
with open('backend/_deploy_env.yaml', 'w') as f:
    for k, v in env.items():
        v_escaped = v.replace("'", "''")
        f.write(f"{k}: '{v_escaped}'\n")
print(f'  Generated _deploy_env.yaml with {len(env)} vars')
"@

# ── Step 2: Deploy Backend ────────────────────────────────────────────
Write-Host "`n=== Deploying Backend ===" -ForegroundColor Cyan
Push-Location backend
gcloud run deploy $BACKEND_SERVICE `
  --source . `
  --region $REGION `
  --allow-unauthenticated `
  --port 8080 `
  --memory 1Gi `
  --cpu 1 `
  --timeout 600 `
  --max-instances 3 `
  --min-instances 0 `
  --env-vars-file _deploy_env.yaml
Remove-Item -Force _deploy_env.yaml -ErrorAction SilentlyContinue
Pop-Location

$BACKEND_URL = gcloud run services describe $BACKEND_SERVICE --region $REGION --format="value(status.url)"
Write-Host "`nBackend deployed at: $BACKEND_URL" -ForegroundColor Green

# ── Step 3: Deploy Frontend ───────────────────────────────────────────
Write-Host "`n=== Deploying Frontend ===" -ForegroundColor Cyan

# Read Google Client ID from .env
$GOOGLE_CLIENT_ID = (Get-Content "backend\.env" | Where-Object { $_ -match "^GOOGLE_CLIENT_ID=" }) -replace "^GOOGLE_CLIENT_ID=", ""

Push-Location frontend
gcloud run deploy $FRONTEND_SERVICE `
  --source . `
  --region $REGION `
  --allow-unauthenticated `
  --port 8080 `
  --memory 512Mi `
  --cpu 1 `
  --max-instances 3 `
  --min-instances 0 `
  --set-build-env-vars "VITE_API_URL=$BACKEND_URL,VITE_GOOGLE_CLIENT_ID=$GOOGLE_CLIENT_ID"
Pop-Location

$FRONTEND_URL = gcloud run services describe $FRONTEND_SERVICE --region $REGION --format="value(status.url)"

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  DataLens Deployed Successfully!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Frontend: $FRONTEND_URL" -ForegroundColor Yellow
Write-Host "  Backend:  $BACKEND_URL" -ForegroundColor Yellow
Write-Host "  API Docs: $BACKEND_URL/docs" -ForegroundColor Yellow
Write-Host "  Health:   $BACKEND_URL/health" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Post-deploy steps:" -ForegroundColor Cyan
Write-Host "  1. Add $FRONTEND_URL to Google OAuth 'Authorized JavaScript Origins'"
Write-Host "  2. Add $FRONTEND_URL/login to Google OAuth 'Authorized Redirect URIs'"
Write-Host "  3. Optionally lock CORS_ORIGINS to your frontend URL"
