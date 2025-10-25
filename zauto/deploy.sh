#!/bin/bash
set -e

RESOURCE_GROUP="asset-manager-rg"
PLAN="asset-manager-plan"
APP_NAME="asset-manager-django"
LOCATION="francecentral"

# Move to the project root (parent of zauto)
cd "$(dirname "$0")/.."

echo "🔐 Logging into Azure..."
az login --only-show-errors

echo "🏗️ Ensuring resource group exists..."
if ! az group show --name "$RESOURCE_GROUP" &>/dev/null; then
    az group create --name "$RESOURCE_GROUP" --location "$LOCATION"
    echo "✅ Created resource group: $RESOURCE_GROUP"
else
    echo "ℹ️ Resource group '$RESOURCE_GROUP' already exists. Skipping."
fi

echo "🧱 Ensuring App Service plan exists..."
if ! az appservice plan show --name "$PLAN" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
    az appservice plan create \
        --name "$PLAN" \
        --resource-group "$RESOURCE_GROUP" \
        --sku F1 \
        --is-linux \
        --location "$LOCATION"
    echo "✅ Created App Service plan: $PLAN"
else
    echo "ℹ️ App Service plan '$PLAN' already exists. Skipping."
fi

echo "🌐 Ensuring Web App exists..."
if ! az webapp show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
    az webapp create \
        --resource-group "$RESOURCE_GROUP" \
        --plan "$PLAN" \
        --name "$APP_NAME" \
        --runtime "PYTHON|3.11"
    echo "✅ Created Web App: $APP_NAME"
else
    echo "ℹ️ Web App '$APP_NAME' already exists. Skipping."
fi

# ------------------------------------------
# Upload only git-tracked files
# ------------------------------------------
echo "📦 Preparing Git-tracked files for deployment..."
ZIP_FILE="deploy.zip"
git archive -o "$ZIP_FILE" HEAD
echo "✅ Created archive: $ZIP_FILE (only files tracked by git)"

echo "🚀 Uploading to Azure..."
az webapp up \
    --name "$APP_NAME" \
    --runtime "PYTHON|3.11" \
    --resource-group "$RESOURCE_GROUP" \
    --sku F1 \
    --src-path "$ZIP_FILE" \
    --log

rm "$ZIP_FILE"
echo "🧹 Cleaned up temporary zip."

echo "⚙️ Updating Web App startup configuration..."
az webapp config set \
    --resource-group "$RESOURCE_GROUP" \
    --name "$APP_NAME" \
    --startup-file "python3.11 -m pip install --upgrade pip && pip install -r requirements.txt && python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn --bind=0.0.0.0 main.wsgi:application"

az webapp log config \
    --name asset-manager-django \
    --resource-group asset-manager-rg \
    --application-logging azureblobstorage \
    --storage-account assetmgrdjangostorage \
    --container-name logs

echo "✅ Deployment complete! Your app is live at:"
echo "   https://$APP_NAME.azurewebsites.net"
