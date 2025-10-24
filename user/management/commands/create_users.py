from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from user.models import Role
from common.logging_config import logger


class Command(BaseCommand):
    help = "Create a 'Premium User' role and assign selected users to it."

    def handle(self, *args, **options):
        logger.info("🚀 [create_premium_users] Starting premium user setup...")

        User = get_user_model()
        role_name = "Premium User"
        description = "Users with premium privileges and access to advanced features."

        try:
            # ------------------------------------------------------
            # 1️⃣ Create or update the Premium User role
            # ------------------------------------------------------
            role, created_role = Role.objects.get_or_create(
                name=role_name,
                defaults={"description": description},
            )

            permission_list = [
                "add_account", "change_account", "delete_account", "view_account",
                "view_accounttype", "add_brand", "change_brand", "delete_brand", "view_brand",
                "view_categorygroup", "add_exchangeraterecord", "change_exchangeraterecord",
                "delete_exchangeraterecord", "view_exchangeraterecord", "add_institution",
                "change_institution", "delete_institution", "view_institution", "add_product",
                "change_product", "delete_product", "view_product", "add_purchasecategory",
                "change_purchasecategory", "delete_purchasecategory", "view_purchasecategory",
                "add_store", "change_store", "delete_store", "view_store", "view_currency",
                "view_unit", "add_transaction", "change_transaction", "delete_transaction",
                "view_transaction", "add_transactionitem", "change_transactionitem",
                "delete_transactionitem", "view_transactionitem", "add_attachment",
                "change_attachment", "delete_attachment", "view_attachment", "change_user",
            ]

            role.permissions.set(Permission.objects.filter(codename__in=permission_list))

            if created_role:
                logger.info(f"✅ [create_premium_users] Role '{role_name}' created successfully.")
            else:
                logger.warning(f"⚠️ [create_premium_users] Role '{role_name}' already exists — permissions refreshed.")

            # ------------------------------------------------------
            # 2️⃣ Create or update premium users
            # ------------------------------------------------------
            users = [
                {"email": "kichujyothis@gmail.com", "password": "space", "first_name": "Kichu", "last_name": "Jyothis"},
                {"email": "kalligerist@gmail.com", "password": "ThanosPassword", "first_name": "Thanos", "last_name": "Kalligeris"},
                {"email": "aditivinayakan@gmail.com", "password": "AmmuPassword", "first_name": "Aditi", "last_name": "Vinayakan"},
                {"email": "tonykokkad@gmail.com", "password": "TonyPassword", "first_name": "Tony", "last_name": "Joy"},
            ]

            for user_data in users:
                email = user_data["email"]
                user, created_user = User.objects.get_or_create(email=email, is_staff=True)

                if created_user:
                    user.set_password(user_data["password"])
                    user.is_superuser = False
                    user.first_name = user_data.get("first_name", "")
                    user.last_name = user_data.get("last_name", "")
                    user.save()
                    user.roles.add(role)
                    logger.info(f"✅ [create_premium_users] User '{email}' created and assigned to '{role_name}'.")
                else:
                    if not user.roles.filter(name=role_name).exists():
                        user.roles.add(role)
                        logger.info(f"🔄 [create_premium_users] User '{email}' updated with '{role_name}' role.")
                    else:
                        logger.warning(f"⚠️ [create_premium_users] User '{email}' already exists with role '{role_name}'.")

            logger.info("🎯 [create_premium_users] Premium user setup completed successfully.")

        except Exception as e:
            logger.exception("🔥 [create_premium_users] Failed during premium user setup:")
            raise e
