#!/bin/bash
# set -e  # stop on first error

# Base dir (project root)
BASE_DIR="$(dirname "$0")"

echo "🧹 Cleaning migrations and database..."
rm -rf "$BASE_DIR"/account/migrations/* "$BASE_DIR"/ai/migrations/* "$BASE_DIR"/analytics/migrations/* "$BASE_DIR"/catalog/migrations/*
rm -rf "$BASE_DIR"/common/migrations/* "$BASE_DIR"/transaction/migrations/* "$BASE_DIR"/user/migrations/*
rm -f "$BASE_DIR"/db.sqlite3
rm -rf "$BASE_DIR"/media/bills/*

echo "📦 Installing dependencies..."
pip install -r "$BASE_DIR"/requirements.txt

echo "💾 Exporting data from money_android.sqlite..."
sqlite3 -json "$BASE_DIR"/money_android.sqlite "SELECT * FROM AssetGroup;" > "$BASE_DIR"/assetgroup.json 
sqlite3 -json "$BASE_DIR"/money_android.sqlite "SELECT * FROM Assets;" > "$BASE_DIR"/assets.json
sqlite3 -json "$BASE_DIR"/money_android.sqlite "SELECT * FROM INOUTCOME;" > "$BASE_DIR"/transactions.json
sqlite3 -json "$BASE_DIR"/money_android.sqlite "SELECT * FROM ZCATEGORY;" > "$BASE_DIR"/category.json

echo "🧱 Applying Django migrations..."
python "$BASE_DIR"/manage.py makemigrations user common catalog account transaction ai
python "$BASE_DIR"/manage.py migrate

echo "🌱 Populating reference data..."
python "$BASE_DIR"/manage.py populate_categories
python "$BASE_DIR"/manage.py populate_units
python "$BASE_DIR"/manage.py populate_currencies

echo "👑 Creating admin user..."
python "$BASE_DIR"/manage.py create_admin

echo "📁 Collecting static files..."
python "$BASE_DIR"/manage.py collectstatic --noinput

echo "⬇️ Importing legacy data..."
python "$BASE_DIR"/manage.py import_legacy_assets --assetgroup "$BASE_DIR"/assetgroup.json --assets "$BASE_DIR"/assets.json --transactions "$BASE_DIR"/transactions.json --categories "$BASE_DIR"/category.json

echo "🛒 Importing grocery CSV..."
python "$BASE_DIR"/manage.py import_grocery_csv "$BASE_DIR"/NetherlandsGrocery.csv

echo "💱 Fetching latest currency rates..."
python "$BASE_DIR"/manage.py fetch_currency_rate

echo "🚀 Starting development server..."
python "$BASE_DIR"/manage.py runserver
