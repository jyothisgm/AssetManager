from django.core.management.base import BaseCommand
from catalog.models import CategoryGroup, PurchaseCategory
from common.logging_config import logger


CATEGORY_STRUCTURE = {
    "Food": ["Restaurant", "Take out", "Delivery", "Fast Food", "Supermarket Food"],
    "Social and Entertainment": [
        "Alcohol", "Movie", "Weed", "Books", "Apps", "Museum", "Gift", "Event"
    ],
    "Education": ["Schooling", "School Supplies", "School Application"],
    "Transport": [
        "Bus", "Subway", "Car", "Visa", "Airlines", "Locker",
        "Facilities", "Train", "Bike", "Taxi"
    ],
    "Household": [
        "Appliances", "Furniture", "Grocery", "Toiletries", "HouseHunting",
        "Mobile", "Bank Fee", "Laundry", "Rent", "Tax", "Internet",
        "Rent Deposit", "Cleaning Supplies", "Tools"
    ],
    "SelfCare": [
        "Clothing", "Shoes", "Gym", "Saloon", "Medicine",
        "Hospital", "Insurance", "Sports", "Games"
    ],
    "Electronics": [],
    "Nicotine": [],
    "Pets": [],
    "Other": [],
    "Credit": [
        "Tips", "Cashback", "Refund", "Salary", "Investment",
        "Gifts Received", "Allowance", "Interest"
    ],
}


class Command(BaseCommand):
    help = "Preload default category groups and their categories."

    def handle(self, *args, **options):
        logger.info("🚀 [populate_categories] Starting category population...")

        created_groups = 0
        created_categories = 0

        try:
            for group_name, categories in CATEGORY_STRUCTURE.items():
                group, group_created = CategoryGroup.objects.get_or_create(name=group_name)
                created_groups += 1
                logger.debug(f"🧩 [populate_categories] Processing group: {group_name}")

                # Create parent category for empty groups
                if not categories:
                    _, cat_created = PurchaseCategory.objects.get_or_create(name=group_name, group=group)
                    created_categories += 1
                    if cat_created:
                        logger.debug(f"➕ [populate_categories] Created parent category '{group_name}'")

                # Create all subcategories
                for cat_name in categories:
                    _, cat_created = PurchaseCategory.objects.get_or_create(name=cat_name, group=group)
                    created_categories += 1
                    if cat_created:
                        logger.debug(f"➕ [populate_categories] Created category '{cat_name}' under '{group_name}'")

            logger.info(
                f"✅ [populate_categories] Created/linked {created_categories} purchase categories across {created_groups} groups."
            )

        except Exception as e:
            logger.exception("🔥 [populate_categories] Failed during category population:")
            raise e

        logger.info("🎯 [populate_categories] Completed successfully.")
