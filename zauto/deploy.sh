#!/bin/bash
set -e

# ===============================================
# ⚙️  Azure Django App Deployment Script
# ===============================================
RESOURCE_GROUP="asset-manager-rg"
PLAN="asset-manager-plan"
APP_NAME="asset-manager-django"
STORAGE_ACCOUNT="assetmgrdjangostorage"
CONTAINER_MEDIA="media"
CONTAINER_STATIC="static"
CONTAINER_LOGS="logs"
SQL_SERVER="assetmgr-sqlserver"
SQL_DB="assetmgr-db"
SQL_ADMIN_USER="django_admin"
SQL_ADMIN_PASS="VnRsoOTG09jpbhSgzVUPetBmUbD3Qj"
LOCATION="francecentral"

# Move to the project root (parent of zauto)
cd "$(dirname "$0")/.."

# -----------------------------------------------
echo "🔐 Logging into Azure..."
az login --only-show-errors

# -----------------------------------------------
echo "🏗️ Ensuring resource group exists..."
if ! az group show --name "$RESOURCE_GROUP" &>/dev/null; then
    az group create --name "$RESOURCE_GROUP" --location "$LOCATION"
    echo "✅ Created resource group: $RESOURCE_GROUP"
else
    echo "ℹ️ Resource group '$RESOURCE_GROUP' already exists. Skipping."
fi

# -----------------------------------------------
echo "🧱 Ensuring App Service plan exists..."
if ! az appservice plan show --name "$PLAN" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
    az appservice plan create \
        --name "$PLAN" \
        --resource-group "$RESOURCE_GROUP" \
        --sku B1 \
        --is-linux \
        --location "$LOCATION"
    echo "✅ Created App Service plan: $PLAN"
else
    echo "ℹ️ App Service plan '$PLAN' already exists. Skipping."
fi

# -----------------------------------------------
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

# ===============================================
# ☁️  STORAGE ACCOUNT + BLOB CONTAINERS
# ===============================================
echo "📦 Ensuring Azure Storage Account exists..."
if ! az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
    az storage account create \
        --name "$STORAGE_ACCOUNT" \
        --resource-group "$RESOURCE_GROUP" \
        --location "$LOCATION" \
        --sku Standard_LRS \
        --kind StorageV2
    echo "✅ Created storage account: $STORAGE_ACCOUNT"
else
    echo "ℹ️ Storage account '$STORAGE_ACCOUNT' already exists. Skipping."
fi

STORAGE_KEY=$(az storage account keys list \
    --resource-group "$RESOURCE_GROUP" \
    --account-name "$STORAGE_ACCOUNT" \
    --query "[0].value" -o tsv)

echo "🪣 Ensuring Blob containers exist..."
for container in "$CONTAINER_MEDIA" "$CONTAINER_STATIC" "$CONTAINER_LOGS"; do
    if ! az storage container show --account-name "$STORAGE_ACCOUNT" --account-key "$STORAGE_KEY" --name "$container" &>/dev/null; then
        az storage container create \
            --name "$container" \
            --account-name "$STORAGE_ACCOUNT" \
            --account-key "$STORAGE_KEY" \
            --public-access blob
        echo "✅ Created container: $container"
    else
        echo "ℹ️ Container '$container' already exists. Skipping."
    fi
done

# ===============================================
# 🧠  SQL DATABASE SETUP
# ===============================================
echo "🧩 Ensuring Azure SQL Server exists..."
if ! az sql server show --name "$SQL_SERVER" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
    az sql server create \
        --name "$SQL_SERVER" \
        --resource-group "$RESOURCE_GROUP" \
        --location "$LOCATION" \
        --admin-user "$SQL_ADMIN_USER" \
        --admin-password "$SQL_ADMIN_PASS"
    echo "✅ Created SQL Server: $SQL_SERVER"
else
    echo "ℹ️ SQL Server '$SQL_SERVER' already exists. Skipping."
fi

echo "💾 Ensuring Azure SQL Database exists..."
if ! az sql db show --name "$SQL_DB" --server "$SQL_SERVER" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
    az sql db create \
        --name "$SQL_DB" \
        --server "$SQL_SERVER" \
        --resource-group "$RESOURCE_GROUP" \
        --service-objective Basic
    echo "✅ Created SQL Database: $SQL_DB"
else
    echo "ℹ️ SQL Database '$SQL_DB' already exists. Skipping."
fi

# Allow Azure services to access the database
az sql server firewall-rule create \
    --resource-group "$RESOURCE_GROUP" \
    --server "$SQL_SERVER" \
    --name "AllowAzureServices" \
    --start-ip-address 0.0.0.0 \
    --end-ip-address 0.0.0.0 \
    >/dev/null

SQL_CONN_STR="Server=tcp:$SQL_SERVER.database.windows.net,1433;Database=$SQL_DB;User ID=$SQL_ADMIN_USER;Password=$SQL_ADMIN_PASS;Encrypt=true;Connection Timeout=30;"

# ===============================================
# 🌍  DEPLOYMENT
# ===============================================
echo "📦 Preparing Git-tracked files for deployment..."
ZIP_FILE="deploy.zip"
git archive -o "$ZIP_FILE" HEAD
echo "✅ Created archive: $ZIP_FILE"

echo "🚀 Uploading to Azure..."
az webapp up \
    --name "$APP_NAME" \
    --runtime "PYTHON|3.11" \
    --resource-group "$RESOURCE_GROUP" \
    --src-path "$ZIP_FILE" \
    --sku F1 \
    --log

rm "$ZIP_FILE" || true
echo "🧹 Cleaned up temporary zip."

# ===============================================
# 🌍  DEPLOYMENT
# ===============================================
APP_NAME="asset-manager-django"
RESOURCE_GROUP="asset-manager-rg"

echo "📦 Preparing Git-tracked files for deployment..."
git archive -o deploy.zip HEAD
echo "✅ Created archive: deploy.zip"

echo "🚀 Uploading to Azure..."
az webapp deployment source config-zip \
    --resource-group "$RESOURCE_GROUP" \
    --name "$APP_NAME" \
    --src deploy.zip

# ===============================================
# 🔧  CONFIGURE APP SETTINGS
# ===============================================
echo "⚙️ Updating Web App configuration..."
az webapp config appsettings set \
    --resource-group "$RESOURCE_GROUP" \
    --name "$APP_NAME" \
    --settings \
        DJANGO_SETTINGS_MODULE="main.settings" \
        AZURE_STORAGE_ACCOUNT="$STORAGE_ACCOUNT" \
        AZURE_STORAGE_KEY="$STORAGE_KEY" \
        MEDIA_CONTAINER="$CONTAINER_MEDIA" \
        STATIC_CONTAINER="$CONTAINER_STATIC" \
        DATABASE_URL="$SQL_CONN_STR"

echo "⚙️ Setting up startup command..."
az webapp config set \
    --resource-group "$RESOURCE_GROUP" \
    --name "$APP_NAME" \
    --startup-file "python3.11 -m pip install --upgrade pip && pip install -r requirements.txt && python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn --bind=0.0.0.0 main.wsgi:application"

# ===============================================
# 🪵  ENABLE LOGGING
# ===============================================
echo "📜 Configuring logs..."
az webapp log config \
    --name "$APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --application-logging azureblobstorage \
    --storage-account "$STORAGE_ACCOUNT" \
    --container-name "$CONTAINER_LOGS"

# ===============================================
echo "✅ Deployment complete!"
echo "🌍 App URL: https://$APP_NAME.azurewebsites.net"
echo "💾 DB: $SQL_DB @ $SQL_SERVER"
echo "🪣 Storage: https://$STORAGE_ACCOUNT.blob.core.windows.net/"
