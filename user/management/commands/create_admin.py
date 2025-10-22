from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = "Create an admin user (admin@example.com / space) without prompt."

    def handle(self, *args, **options):
        User = get_user_model()
        email = "admin@asset.com"
        password = "space"

        if not User.objects.filter(email=email).exists():
            User.objects.create_superuser(email=email, password=password)
            self.stdout.write(self.style.SUCCESS(f"✅ Superuser '{email}' created with password '{password}'"))
        else:
            self.stdout.write(self.style.WARNING(f"⚠️ Superuser '{email}' already exists."))
