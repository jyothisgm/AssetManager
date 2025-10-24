from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from user.models import Role 

User = get_user_model()


class Command(BaseCommand):
    help = "Create a 'Premium User' role and a user assigned to that role."

    def handle(self, *args, **options):
        # 1️⃣ Create the Premium User role
        role_name = "Premium User"
        description = "Users with premium privileges and access to advanced features."

        role, created_role = Role.objects.get_or_create(
            name=role_name,
            defaults={"description": description},
        )
        permission_list = ['add_account', 'change_account', 'delete_account', 'view_account', 'view_accounttype', 
                            'add_brand', 'change_brand', 'delete_brand', 'view_brand', 'view_categorygroup', 
                            'add_exchangeraterecord', 'change_exchangeraterecord', 'delete_exchangeraterecord', 
                            'view_exchangeraterecord', 'add_institution', 'change_institution', 'delete_institution', 
                            'view_institution', 'add_product', 'change_product', 'delete_product', 'view_product', 
                            'add_purchasecategory', 'change_purchasecategory', 'delete_purchasecategory', 'view_purchasecategory', 
                            'add_store', 'change_store', 'delete_store', 'view_store', 'view_currency', 'view_unit', 
                            'add_transaction', 'change_transaction', 'delete_transaction', 'view_transaction', 
                            'add_transactionitem', 'change_transactionitem', 'delete_transactionitem', 'view_transactionitem',
                            'add_attachment', 'change_attachment', 'delete_attachment', 'view_attachment', 'change_user']
        role.permissions.set(Permission.objects.filter(codename__in=permission_list))


        if created_role:
            self.stdout.write(self.style.SUCCESS(f"✅ Role '{role_name}' created."))
        else:
            self.stdout.write(self.style.WARNING(f"⚠️ Role '{role_name}' already exists."))

        # 2️⃣ Create the Premium User
        users = [
            {
                "email": "kichujyothis@gmail.com",
                "password": "space",
                "first_name": "Kichu",
                "last_name": "Jyothis"
            },
            {
                "email": "kalligerist@gmail.com",
                "password": "ThanosPassword",
                "first_name": "Thanos",
                "last_name": "Kalligeris"
            },
            {
                "email": "aditivinayakan@gmail.com",
                "password": "AmmuPassword",
                "first_name": "Aditi",
                "last_name": "Vinayakan"
            },
            {
                "email": "tonykokkad@gmail.com",
                "password": "TonyPassword",
                "first_name": "Tony",
                "last_name": "Joy"
            },
        ]
        for each in users:
            user, created_user = User.objects.get_or_create(email=each['email'], is_staff=True)

            if created_user:
                user.set_password(each['password'])
                user.is_superuser = False
                user.roles.add(role)
                user.save()
                self.stdout.write(self.style.SUCCESS(f"✅ User '{each['email']}' created."))
            else:
                self.stdout.write(self.style.WARNING(f"⚠️ User '{each['email']}' already exists."))

