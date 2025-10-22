# rm -rf account/migrations/* ai/migrations/* analytics/migrations/* catalog/migrations/* 
# rm -rf common/migrations/* transaction/migrations/* user/migrations/* 
pip install -r requirements.txt

rm -rf db.sqlite3 media/bills/*

sqlite3 -json money_android.sqlite "SELECT * FROM AssetGroup;" > assetgroup.json 
sqlite3 -json money_android.sqlite "SELECT * FROM Assets;" > assets.json
sqlite3 -json money_android.sqlite "SELECT * FROM INOUTCOME;" > transactions.json
sqlite3 -json money_android.sqlite "SELECT * FROM ZCATEGORY;" > category.json

python manage.py makemigrations user common catalog account transaction ai

python manage.py migrate
python manage.py populate_categories
python manage.py populate_units
python manage.py populate_currencies

python manage.py create_admin

python manage.py collectstatic --noinput

python manage.py import_legacy_assets --assetgroup assetgroup.json --assets assets.json --transactions transactions.json --categories category.json
python manage.py import_grocery_csv "NetherlandsGrocery.csv"
python manage.py fetch_currency_rate

python manage.py runserver
