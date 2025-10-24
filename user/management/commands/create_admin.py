from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from common.logging_config import logger


class Command(BaseCommand):
    help = "Create a default admin user (admin@asset.com / space) if not already present."

    def handle(self, *args, **options):
        logger.info("🚀 [create_admin] Checking for existing superuser...")

        User = get_user_model()
        email = "admin@asset.com"
        password = "space"

        try:
            if not User.objects.filter(email=email).exists():
                User.objects.create_superuser(email=email, password=password)
                logger.info(f"✅ [create_admin] Superuser '{email}' created successfully.")
            else:
                logger.warning(f"⚠️ [create_admin] Superuser '{email}' already exists.")
        except Exception as e:
            logger.exception("🔥 [create_admin] Failed to create admin user:")
            raise e

        logger.info("🎯 [create_admin] Completed successfully.")
