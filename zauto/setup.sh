# rm -rf */migrations/*.py */migrations/*.pyc 2>/dev/null
# rm -rf db.sqlite3 media/bills/*

# sqlite3 -json money_android.sqlite "SELECT * FROM AssetGroup;" > assetgroup.json 
# sqlite3 -json money_android.sqlite "SELECT * FROM Assets;" > assets.json
# sqlite3 -json money_android.sqlite "SELECT * FROM INOUTCOME;" > transactions.json
# sqlite3 -json money_android.sqlite "SELECT * FROM ZCATEGORY;" > category.json

# python manage.py makemigrations user common catalog account transaction ai
# python manage.py migrate


# -------------------------------
# 1️⃣  Populate Base Reference Data
# -------------------------------
python manage.py populate_categories
python manage.py populate_units
python manage.py populate_currencies
python manage.py create_admin
python manage.py create_users
python manage.py collectstatic --noinput
python manage.py import_legacy_assets \
    --assetgroup zauto/initial_data/assetgroup.json \
    --assets zauto/initial_data/assets.json \
    --transactions zauto/initial_data/transactions.json \
    --categories zauto/initial_data/category.json
python manage.py import_grocery_csv "zauto/initial_data/NetherlandsGrocery.csv"
python manage.py fetch_currency_rate
