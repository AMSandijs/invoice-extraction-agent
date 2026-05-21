#!/bin/bash
# Deploy the Invoice Assistant Streamlit app to Azure Container Apps.
#
# Prerequisites:
#   az login
#   tofu init  (first time only, inside infra/)
#
# Usage: ./deploy.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "==> Step 1/3: Provisioning Azure infrastructure..."
cd "$REPO_ROOT/infra"
tofu apply -auto-approve

ACR_NAME=$(tofu output -raw acr_name)
ACR_SERVER=$(tofu output -raw acr_login_server)
CA_NAME=$(tofu output -raw container_app_name)
RG_NAME=$(tofu output -raw resource_group)
APP_URL=$(tofu output -raw app_url)

echo ""
echo "==> Step 2/3: Building and pushing Docker image to ACR (~2 minutes)..."
cd "$REPO_ROOT"
az acr build \
  --registry "$ACR_NAME" \
  --image "invoice-agent:latest" \
  --file Dockerfile \
  .

echo ""
echo "==> Step 3/3: Wiring ACR credentials and deploying the real image..."
# Configure the Container App to pull from ACR using its managed identity.
az containerapp registry set \
  --name "$CA_NAME" \
  --resource-group "$RG_NAME" \
  --server "$ACR_SERVER" \
  --identity system \
  --output none

# Swap in the real image and keep it always running (min 1 replica).
az containerapp update \
  --name "$CA_NAME" \
  --resource-group "$RG_NAME" \
  --image "${ACR_SERVER}/invoice-agent:latest" \
  --min-replicas 1 \
  --output none

echo ""
echo "=========================================="
echo "  Deployment complete!"
echo "  App URL: $APP_URL"
echo "=========================================="
echo ""
echo "The app may take ~30 seconds to start on the first visit."
