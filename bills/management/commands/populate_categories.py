from django.core.management.base import BaseCommand
from bills.models import CategoryGroup, PurchaseCategory

CATEGORY_STRUCTURE = {
    "Food": [
        "Restaurant",
        "Take out",
        "Delivery",
        "Fast Food",
        "Supermarket"
    ],
    "Social and Entertainment": [
        "Alcohol",
        "Movies",
        "Weed",
        "Books",
        "Apps",
        "Museum",
        "Gifts",
        "Electronics",  # shared
    ],
    "Education": [
        "Schooling",
        "Supplies",
        "Books",
        "Electronics",  # shared
    ],
    "Transport": [
        "Bus",
        "Subway",
        "Car",
        "Visa",
        "Airlines",
        "Locker",
        "Facilities",
        "Train",
        "Bike",
    ],
    "Household": [
        "Appliances",
        "Furniture",
        "Grocery",
        "Toiletries",
        "HouseHunting",
        "Mobile",
        "Bank Fees",
        "Laundry",
        "Rent",
        "Tax",
        "Internet",
        "Rent Deposit",
        "Cleaning Supplies",
        "Tools",
        "Electronics",  # shared
    ],
    "SelfCare": [
        "Clothing",
        "Shoes",
        "Gym",
        "Saloon",
        "Medicine",
        "Hospital",
        "Insurance",
        "Sports",
        "Games",
        "Electronics",  # shared
    ],
    "Nicotine": [],
    "Pets": [],
    "Others": [],
}


class Command(BaseCommand):
    help = "Preload default category groups and their categories."

    def handle(self, *args, **options):
        created_groups = 0
        created_categories = 0

        for group_name, categories in CATEGORY_STRUCTURE.items():
            group, _ = CategoryGroup.objects.get_or_create(name=group_name)
            created_groups += 1

            # ✅ Only create a PurchaseCategory for groups that have no subcategories
            if not categories:
                parent_cat, _ = PurchaseCategory.objects.get_or_create(name=group_name)
                parent_cat.groups.add(group)
                parent_cat.save()
                created_categories += 1

            # Create and attach all subcategories
            for cat_name in categories:
                cat, _ = PurchaseCategory.objects.get_or_create(name=cat_name)
                cat.groups.add(group)
                cat.save()
                created_categories += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"✅ Created/linked {created_categories} purchase categories across {created_groups} groups (including empty groups)."
            )
        )
