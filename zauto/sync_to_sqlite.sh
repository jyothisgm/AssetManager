#!/bin/bash
set -e

# Script to download all data from Azure SQL Server and import into SQLite
# Usage: ./zauto/sync_to_sqlite.sh [--fetch-latest] [--clear-sqlite]
#
# Options:
#   --fetch-latest  : Fetch latest data from Azure SQL Server (default: use existing fixture)
#   --clear-sqlite  : Clear existing SQLite data before import

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

EXPORT_FILE="zauto/fixtures/server_data_export.json"

# Check flags
FETCH_LATEST=false
CLEAR_SQLITE=false

for arg in "$@"; do
    case $arg in
        --fetch-latest)
            FETCH_LATEST=true
            shift
            ;;
        --clear-sqlite)
            CLEAR_SQLITE=true
            shift
            ;;
        *)
            # Unknown option
            ;;
    esac
done

echo "🔄 Syncing data from server to SQLite..."
echo ""

# Step 1: Export from Azure (if --fetch-latest flag is set)
if [ "$FETCH_LATEST" = true ]; then
    echo "📥 Step 1: Exporting latest data from Azure SQL Server..."
    export DJANGO_ENV=AZURE
    python manage.py sync_server_to_sqlite --output-file "$EXPORT_FILE"
    
    if [ ! -f "$EXPORT_FILE" ]; then
        echo "❌ Export failed: $EXPORT_FILE not found"
        exit 1
    fi
    
    echo ""
    echo "✅ Export complete!"
    echo ""
else
    echo "ℹ️  Step 1: Using existing fixture file (use --fetch-latest to get latest data)"
    
    if [ ! -f "$EXPORT_FILE" ]; then
        echo "❌ Export file not found: $EXPORT_FILE"
        echo "   Run with --fetch-latest to download from server first"
        exit 1
    fi
    
    # Show file modification time
    if command -v stat >/dev/null 2>&1; then
        if [[ "$OSTYPE" == "darwin"* ]]; then
            # macOS
            MOD_TIME=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M:%S" "$EXPORT_FILE" 2>/dev/null || echo "unknown")
        else
            # Linux
            MOD_TIME=$(stat -c "%y" "$EXPORT_FILE" 2>/dev/null | cut -d'.' -f1 || echo "unknown")
        fi
        echo "   File last modified: $MOD_TIME"
    fi
    echo ""
fi

# Step 2: Import into SQLite
echo "📤 Step 2: Importing data into SQLite..."
unset DJANGO_ENV
# Or explicitly set: export DJANGO_ENV=local

# Build import command
IMPORT_CMD="python manage.py sync_server_to_sqlite --import-only \"$EXPORT_FILE\""

if [ "$CLEAR_SQLITE" = true ]; then
    IMPORT_CMD="$IMPORT_CMD --clear-sqlite"
    echo "⚠️  Will clear existing SQLite data before import"
fi

eval $IMPORT_CMD

echo ""
echo "✅ Sync complete!"
echo "📁 Fixture file: $EXPORT_FILE"
echo "💾 SQLite database: assetmanager.sqlite"

