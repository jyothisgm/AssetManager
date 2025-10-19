rm -rf bills/migrations/* db.sqlite3 media/bills/*
python manage.py makemigrations bills

python manage.py migrate
python manage.py populate_categories
python manage.py populate_units
python manage.py create_admin
python manage.py collectstatic --noinput
python manage.py import_bills_csv "NetherlandsGrocery.csv"


python manage.py runserver