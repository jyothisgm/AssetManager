#!/bin/bash
set -e

# Script to add or remove IP address from Azure SQL Server firewall
# Usage: 
#   ./zauto/add_firewall_rule.sh              # Add current IP
#   ./zauto/add_firewall_rule.sh --remove     # Remove current IP
#   ./zauto/add_firewall_rule.sh --remove --ip 1.2.3.4  # Remove specific IP

RESOURCE_GROUP="asset-manager-rg"
SQL_SERVER="asset-manager-sqlserver"

# Parse arguments
REMOVE_MODE=false
SPECIFIC_IP=""

for arg in "$@"; do
    case $arg in
        --remove|--delete)
            REMOVE_MODE=true
            shift
            ;;
        --ip)
            SPECIFIC_IP="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

echo "🔐 Logging into Azure..."
az login --only-show-errors

# Get IP address
if [ -n "$SPECIFIC_IP" ]; then
    CURRENT_IP="$SPECIFIC_IP"
    echo "🌐 Using specified IP address: $CURRENT_IP"
else
    echo "🌐 Getting your current public IP address..."
    CURRENT_IP=$(curl -s https://api.ipify.org)
    echo "   Your IP: $CURRENT_IP"
fi

# Create firewall rule name based on IP
RULE_NAME="allow-ip-$(echo $CURRENT_IP | tr '.' '-')"

if [ "$REMOVE_MODE" = true ]; then
    echo "🗑️  Removing firewall rule for IP: $CURRENT_IP..."
    
    az sql server firewall-rule delete \
        --resource-group "$RESOURCE_GROUP" \
        --server "$SQL_SERVER" \
        --name "$RULE_NAME" \
        --yes \
        >/dev/null 2>&1
    
    if [ $? -eq 0 ]; then
        echo "✅ Firewall rule removed successfully!"
        echo "   Rule name: $RULE_NAME"
        echo "   IP address: $CURRENT_IP"
    else
        echo "⚠️  Firewall rule not found or already removed."
        echo "   Rule name: $RULE_NAME"
        echo "   IP address: $CURRENT_IP"
    fi
    
    echo ""
    echo "📋 Remaining firewall rules:"
    az sql server firewall-rule list \
        --resource-group "$RESOURCE_GROUP" \
        --server "$SQL_SERVER" \
        --output table
    exit 0
fi

echo "🔥 Adding firewall rule for IP: $CURRENT_IP..."

az sql server firewall-rule create \
    --resource-group "$RESOURCE_GROUP" \
    --server "$SQL_SERVER" \
    --name "$RULE_NAME" \
    --start-ip-address "$CURRENT_IP" \
    --end-ip-address "$CURRENT_IP" \
    >/dev/null 2>&1

if [ $? -eq 0 ]; then
    echo "✅ Firewall rule added successfully!"
    echo "   Rule name: $RULE_NAME"
    echo "   IP address: $CURRENT_IP"
    echo ""
    echo "⏳ Note: It may take up to 5 minutes for the change to take effect."
else
    echo "⚠️  Firewall rule might already exist, or there was an error."
    echo "   Trying to update existing rule..."
    
    az sql server firewall-rule update \
        --resource-group "$RESOURCE_GROUP" \
        --server "$SQL_SERVER" \
        --name "$RULE_NAME" \
        --start-ip-address "$CURRENT_IP" \
        --end-ip-address "$CURRENT_IP" \
        >/dev/null 2>&1
    
    if [ $? -eq 0 ]; then
        echo "✅ Firewall rule updated successfully!"
    else
        echo "❌ Failed to add/update firewall rule."
        echo "   You may need to add it manually via Azure Portal:"
        echo "   https://portal.azure.com -> SQL Servers -> $SQL_SERVER -> Networking"
        exit 1
    fi
fi

echo ""
echo "📋 Current firewall rules:"
az sql server firewall-rule list \
    --resource-group "$RESOURCE_GROUP" \
    --server "$SQL_SERVER" \
    --output table

