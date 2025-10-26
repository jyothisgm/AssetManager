RESOURCE_GROUP="asset-manager-rg"
PLAN="asset-manager-plan"
APP_NAME="asset-manager-django"
LOCATION="francecentral"

# Storage
STORAGE_ACCOUNT="assetmgrdjangostorage"
CONTAINER_MEDIA="media"
CONTAINER_LOGS="logs"

# Azure SQL
SQL_SERVER="assetmgr-sqlserver"
SQL_DB="assetmgr-db"
SQL_ADMIN_USER="django_admin"
SQL_ADMIN_PASS="VnRsoOTG09jpbhSgzVUPetBmUbD3Qj"


az group create --name "$RESOURCE_GROUP" --location "$LOCATION"


# B1 is a small paid tier; F1 free is limited and often throttled.
az appservice plan create \
  --name "$PLAN" \
  --resource-group "$RESOURCE_GROUP" \
  --sku B1 \
  --is-linux \
  --location "$LOCATION"


az webapp create \
  --resource-group "$RESOURCE_GROUP" \
  --plan "$PLAN" \
  --name "$APP_NAME" \
  --runtime "PYTHON|3.11"


az storage account create \
  --name "$STORAGE_ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --sku Standard_LRS \
  --kind StorageV2


STORAGE_KEY=$(az storage account keys list \
  --resource-group "$RESOURCE_GROUP" \
  --account-name "$STORAGE_ACCOUNT" \
  --query "[0].value" -o tsv)


# Create private containers (no --public-access flag)
az storage container create \
  --name media \
  --account-name "$STORAGE_ACCOUNT" \
  --account-key "$STORAGE_KEY"

az storage container create \
  --name logs \
  --account-name "$STORAGE_ACCOUNT" \
  --account-key "$STORAGE_KEY"



az sql server create \
  --name "$SQL_SERVER" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --admin-user "$SQL_ADMIN_USER" \
  --admin-password "$SQL_ADMIN_PASS"


az sql db create \
  --name "$SQL_DB" \
  --server "$SQL_SERVER" \
  --resource-group "$RESOURCE_GROUP" \
  --service-objective Basic


az sql server firewall-rule create \
  --resource-group "$RESOURCE_GROUP" \
  --server "$SQL_SERVER" \
  --name "AllowAzureServices" \
  --start-ip-address 0.0.0.0 \
  --end-ip-address 0.0.0.0

az sql server firewall-rule create \
  --resource-group asset-manager-rg \
  --server asset-manager-sqlserver \
  --name AllowLocalIP \
  --start-ip-address $(curl -s https://api.ipify.org) \
  --end-ip-address $(curl -s https://api.ipify.org)
