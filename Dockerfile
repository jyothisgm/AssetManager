# Start with lightweight Python image
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files
COPY . .

# Run migrations and collect static files during build
RUN python manage.py migrate --noinput
RUN python manage.py collectstatic --noinput

# Optional: create admin user (if you want one baked in)
# RUN echo "from django.contrib.auth import get_user_model; User = get_user_model(); User.objects.create_superuser('admin', '', 'password')" | python manage.py shell

# Expose Django app via Gunicorn
CMD gunicorn main.wsgi:application --bind 0.0.0.0:$PORT
