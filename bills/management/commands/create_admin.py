from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    help = "Create an admin user (admin / yourpassword) without prompt."

    def handle(self, *args, **options):
        User = get_user_model()
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser("admin", "", "space")
            self.stdout.write(self.style.SUCCESS("✅ Superuser 'admin' created."))
        else:
            self.stdout.write("⚠️ Superuser 'admin' already exists.")
