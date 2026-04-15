#!/bin/bash
# ============================================================================
# DataLens Analytics — Google Cloud Run Deployment Script (Linux/macOS)
# ============================================================================
#
# Prerequisites:
#   1. Install gcloud CLI: https://cloud.google.com/sdk/docs/install
#   2. Authenticate: gcloud auth login
#   3. Copy backend/.env.example → backend/.env and fill in your secrets
#   4. Copy frontend/.env.example → frontend/.env and fill in your values
#
# Usage:
#   chmod +x deploy.sh
#   ./deploy.sh
# ============================================================================
set -e

# ── Configuration (edit these) ────────────────────────────────────────
PROJECT_ID="${GCP_PROJECT_ID:-your-gcp-project-id}"
REGION="${GCP_REGION:-asia-south1}"
BACKEND_SERVICE="datalens-api"
FRONTEND_SERVICE="datalens-app"

echo "=== DataLens Deployment ==="
echo "  Project: $PROJECT_ID"
echo "  Region:  $REGION"
echo ""

# Validate that .env exists
if [ ! -f backend/.env ]; then
  echo "ERROR: backend/.env not found. Copy backend/.env.example and fill in your secrets."
  exit 1
fi

gcloud config set project "$PROJECT_ID"

# ── Step 1: Generate env-vars YAML from .env ──────────────────────────
echo "=== Generating deployment env vars ==="
python3 -c "
import json
env = {}
with open('backend/.env') as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, _, val = line.partition('=')
        env[key.strip()] = val.strip()
# Ensure CORS_ORIGINS is valid JSON for pydantic
if 'CORS_ORIGINS' in env:
    try:
        json.loads(env['CORS_ORIGINS'])
    except json.JSONDecodeError:
        env['CORS_ORIGINS'] = '[\"*\"]'
with open('backend/_deploy_env.yaml', 'w') as f:
    for k, v in env.items():
        v_escaped = v.replace(\"'\", \"''\")
        f.write(f\"{k}: '{v_escaped}'\n\")
print(f'  Generated _deploy_env.yaml with {len(env)} vars')
"

# ── Step 2: Deploy Backend ────────────────────────────────────────────
echo ""
echo "=== Deploying Backend ==="
cd backend
gcloud run deploy "$BACKEND_SERVICE" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --port 8080 \
  --memory 1Gi \
  --cpu 1 \
  --timeout 600 \
  --max-instances 3 \
  --min-instances 0 \
  --env-vars-file _deploy_env.yaml
rm -f _deploy_env.yaml
cd ..

BACKEND_URL=$(gcloud run services describe "$BACKEND_SERVICE" --region "$REGION" --format="value(status.url)")
echo ""
echo "Backend deployed at: $BACKEND_URL"

# ── Step 3: Deploy Frontend ───────────────────────────────────────────
echo ""
echo "=== Deploying Frontend ==="

# Read Google Client ID from backend .env
GOOGLE_CLIENT_ID=$(grep "^GOOGLE_CLIENT_ID=" backend/.env | cut -d= -f2-)

cd frontend
gcloud run deploy "$FRONTEND_SERVICE" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --port 8080 \
  --memory 512Mi \
  --cpu 1 \
  --max-instances 3 \
  --min-instances 0 \
  --set-build-env-vars "VITE_API_URL=$BACKEND_URL,VITE_GOOGLE_CLIENT_ID=$GOOGLE_CLIENT_ID"
cd ..

FRONTEND_URL=$(gcloud run services describe "$FRONTEND_SERVICE" --region "$REGION" --format="value(status.url)")

echo ""
echo "============================================"
echo "  DataLens Deployed Successfully!"
echo "============================================"
echo "  Frontend: $FRONTEND_URL"
echo "  Backend:  $BACKEND_URL"
echo "  API Docs: $BACKEND_URL/docs"
echo "  Health:   $BACKEND_URL/health"
echo "============================================"
echo ""
echo "Post-deploy steps:"
echo "  1. Add $FRONTEND_URL to Google OAuth 'Authorized JavaScript Origins'"
echo "  2. Add $FRONTEND_URL/login to Google OAuth 'Authorized Redirect URIs'"
echo "  3. Optionally lock CORS_ORIGINS to your frontend URL:"
echo "     gcloud run services update $BACKEND_SERVICE --region $REGION \\"
echo "       --update-env-vars 'CORS_ORIGINS=[\"$FRONTEND_URL\",\"http://localhost:5174\"]'"
