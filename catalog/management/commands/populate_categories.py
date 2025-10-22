from django.core.management.base import BaseCommand
from catalog.models import CategoryGroup, PurchaseCategory

CATEGORY_STRUCTURE = {
    "Food": [
        "Restaurant",
        "Take out",
        "Delivery",
        "Fast Food",
        "Supermarket Food"
    ],
    "Social and Entertainment": [
        "Alcohol",
        "Movie",
        "Weed",
        "Books",
        "Apps",
        "Museum",
        "Gift",
        "Event"
    ],
    "Education": [
        "Schooling",
        "School Supplies",
        "School Application"
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
        "Taxi"
    ],
    "Household": [
        "Appliances",
        "Furniture",
        "Grocery",
        "Toiletries",
        "HouseHunting",
        "Mobile",
        "Bank Fee",
        "Laundry",
        "Rent",
        "Tax",
        "Internet",
        "Rent Deposit",
        "Cleaning Supplies",
        "Tools",
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
    ],
    "Electronics": [],
    "Nicotine": [],
    "Pets": [],
    "Other": [],
    "Credit": [
        'Tips', 
        'Cashback', 
        'Refund', 
        'Salary', 
        'Investment', 
        'Gifts Received', 
        'Allowance', 
        'Interest'
    ],
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
                parent_cat, _ = PurchaseCategory.objects.get_or_create(name=group_name, group=group)
                created_categories += 1

            # Create and attach all subcategories
            for cat_name in categories:
                cat, _ = PurchaseCategory.objects.get_or_create(name=cat_name, group=group)
                created_categories += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"✅ Created/linked {created_categories} purchase categories across {created_groups} groups (including empty groups)."
            )
        )
