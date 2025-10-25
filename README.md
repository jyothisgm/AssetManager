````markdown
# 🚀 Asset Manager — Azure Deployment Guide

This guide explains how to deploy the **Django-based Asset Manager** application on **Microsoft Azure App Service (Linux)** with an **MSSQL database** and **Blob Storage** for media files.

---

## 🧭 Prerequisites
- [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli)
- Azure account (Free Tier or credits)
- Django app with `requirements.txt`, `main/wsgi.py`, and proper `STATIC_ROOT` / `MEDIA_ROOT`

---

## 🔐 Login
```bash
az login
````

---

## 🏗️ Resource Group

```bash
# Create
az group create --name asset-manager-rg --location francecentral

# Delete
az group delete --name asset-manager-rg --yes --no-wait
```

---

## ⚙️ App Service Plan

```bash
az appservice plan create \
  --name asset-manager-plan \
  --resource-group asset-manager-rg \
  --sku F1 \
  --is-linux \
  --location francecentral
```

---

## 🌐 Web App (Django)

```bash
# Create Web App
az webapp create \
  --resource-group asset-manager-rg \
  --plan asset-manager-plan \
  --name asset-manager-django \
  --runtime "PYTHON|3.11"

# Deploy and Start
git archive -o deploy.zip HEAD
az webapp up \
  --name asset-manager-django \
  --runtime "PYTHON|3.11" \
  --resource-group asset-manager-rg \
  --sku F1 \
  --src-path deploy.zip \
  --log

# Delete
az webapp delete --name asset-manager-django --resource-group asset-manager-rg
```

---

## ⚙️ Startup Command

```bash
az webapp config set \
  --resource-group asset-manager-rg \
  --name asset-manager-django \
  --startup-file "python3.11 -m pip install --upgrade pip && pip install -r requirements.txt && python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn --bind=0.0.0.0 main.wsgi:application"
```

---

## 📋 Environment Variables

```bash
az webapp config appsettings set \
  --name asset-manager-django \
  --resource-group asset-manager-rg \
  --settings \
  DJANGO_SETTINGS_MODULE="main.settings" \
  DEBUG="False" \
  ALLOWED_HOSTS="asset-manager-django.azurewebsites.net"
```

---

## 🧩 Logging

```bash
az webapp log config \
  --name asset-manager-django \
  --resource-group asset-manager-rg \
  --application-logging filesystem \
  --detailed-error-messages true \
  --level information

# Stream logs
az webapp log tail --name asset-manager-django --resource-group asset-manager-rg
```

---

## 🗄️ SQL Database

```bash
# Create SQL Server
az sql server create \
  --name asset-manager-sqlserver \
  --resource-group asset-manager-rg \
  --location francecentral \
  --admin-user adminuser \
  --admin-password "StrongPassword123!"

# Allow Azure Access
az sql server firewall-rule create \
  --resource-group asset-manager-rg \
  --server asset-manager-sqlserver \
  --name AllowLocalIP \
  --start-ip-address $(curl -s https://api.ipify.org) \
  --end-ip-address $(curl -s https://api.ipify.org)

# Create Database
az sql db create \
  --name asset-manager-db \
  --server asset-manager-sqlserver \
  --resource-group asset-manager-rg \
  --service-objective S0

# Delete DB
az sql db delete \
  --name asset-manager-db \
  --server asset-manager-sqlserver \
  --resource-group asset-manager-rg \
  --yes
```

---

## 🪣 Blob Storage

```bash
# Create Storage Account
az storage account create \
  --name assetmgrdjangostorage \
  --resource-group asset-manager-rg \
  --location francecentral \
  --sku Standard_LRS \
  --kind StorageV2

# Create Container
az storage container create \
  --name media \
  --account-name assetmgrdjangostorage \
  --public-access off

# Get Key
az storage account keys list \
  --account-name assetmgrdjangostorage \
  --resource-group asset-manager-rg \
  --query "[0].value" \
  --output tsv
```

### Django Settings

```python
DEFAULT_FILE_STORAGE = "storages.backends.azure_storage.AzureStorage"
AZURE_ACCOUNT_NAME = "assetmgrdjangostorage"
AZURE_ACCOUNT_KEY = "<YOUR_ACCESS_KEY>"
AZURE_CONTAINER = "media"
```

---

## 🧰 Full Deployment Script

```bash
#!/bin/bash
set -e

RESOURCE_GROUP="asset-manager-rg"
PLAN="asset-manager-plan"
APP_NAME="asset-manager-django"
LOCATION="francecentral"

az login
az group create --name $RESOURCE_GROUP --location $LOCATION
az appservice plan create --name $PLAN --resource-group $RESOURCE_GROUP --sku F1 --is-linux
az webapp create --resource-group $RESOURCE_GROUP --plan $PLAN --name $APP_NAME --runtime "PYTHON|3.11"
az webapp config set --resource-group $RESOURCE_GROUP --name $APP_NAME \
  --startup-file "python3.11 -m pip install --upgrade pip && pip install -r requirements.txt && python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn --bind=0.0.0.0 main.wsgi:application"
```

Run:

```bash
chmod +x deploy.sh
./deploy.sh
```

---

## 🧹 Cleanup

```bash
az group delete --name asset-manager-rg --yes --no-wait
```

---

## ✅ Summary

| Component         | Name                      | Command                           |
| ----------------- | ------------------------- | --------------------------------- |
| Resource Group    | `asset-manager-rg`        | `az group create ...`             |
| App Service Plan  | `asset-manager-plan`      | `az appservice plan create ...`   |
| Web App           | `asset-manager-django`    | `az webapp create ...`            |
| SQL Server        | `asset-manager-sqlserver` | `az sql server create ...`        |
| SQL Database      | `asset-manager-db`        | `az sql db create ...`            |
| Storage Account   | `assetmgrdjangostorage`   | `az storage account create ...`   |
| Storage Container | `media`                   | `az storage container create ...` |

---

## 🔗 References

* [Azure App Service for Python](https://learn.microsoft.com/en-us/azure/app-service/quickstart-python)
* [Azure Blob Storage Django Integration](https://pypi.org/project/django-storages/)
* [Azure SQL Database Docs](https://learn.microsoft.com/en-us/azure/azure-sql/)
* [Azure CLI Reference](https://learn.microsoft.com/en-us/cli/azure/reference-index)

---

🟢 **Your Django app will be live at:**
[https://asset-manager-django.azurewebsites.net](https://asset-manager-django.azurewebsites.net)

```
```
