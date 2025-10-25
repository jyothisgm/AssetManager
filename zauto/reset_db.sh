#!/bin/bash
set -e

# ------------------------------------------
# Azure SQL Database Reset Script
# ------------------------------------------

RESOURCE_GROUP="asset-manager-rg"
SQL_SERVER="asset-manager-sqlserver"
SQL_DB="asset-manager-db"
LOCATION="francecentral"

echo "🔐 Logging into Azure..."
az login --only-show-errors

echo "🧩 Checking if SQL Server exists..."
if ! az sql server show --name "$SQL_SERVER" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
    echo "❌ SQL Server '$SQL_SERVER' not found in resource group '$RESOURCE_GROUP'."
    echo "Please create it first using your main deploy.sh script."
    exit 1
fi

echo "💣 Deleting existing database (if any)..."
if az sql db show --name "$SQL_DB" --server "$SQL_SERVER" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
    az sql db delete \
        --name "$SQL_DB" \
        --server "$SQL_SERVER" \
        --resource-group "$RESOURCE_GROUP" \
        --yes
    echo "✅ Deleted existing database: $SQL_DB"
else
    echo "ℹ️ No existing database found. Skipping deletion."
fi

echo "🧱 Creating a fresh database..."
az sql db create \
    --name "$SQL_DB" \
    --server "$SQL_SERVER" \
    --resource-group "$RESOURCE_GROUP" \
    --service-objective S0 \
    --zone-redundant false \
    --backup-storage-redundancy Local

echo "✅ Database reset complete: $SQL_DB"
