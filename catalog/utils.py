from catalog.models import Brand, Product, Store, ProductCategory
from common.logging_config import logger
from django.db import transaction


# ============================================================
# STORES
# ============================================================

def get_or_create_store(raw_name: str, normalized_name: str | None = None, category: ProductCategory | None = None) -> Store | None:
    if not raw_name and not normalized_name:
        logger.warning("[get_or_create_store] Missing both raw_name and normalized_name → returning None")
        return None

    raw_name = raw_name.strip()
    normalized_name = (normalized_name or raw_name).strip()

    try:
        with transaction.atomic():
            # 1️⃣ Check existing store by raw name
            store = Store.objects.filter(name__iexact=raw_name).first()
            if store:
                logger.debug(f"[get_or_create_store] Found existing store '{raw_name}' (id={store.id})")
                return store

            # 2️⃣ Find or create preferred
            preferred_store, created = Store.objects.get_or_create(
                name__iexact=normalized_name,
                defaults={"name": normalized_name}
            )
            if created:
                logger.info(f"[get_or_create_store] Created new preferred store '{normalized_name}' (id={preferred_store.id})")
            if category:
                preferred_store.categories.add(category)

            # 3️⃣ Create variant if raw_name differs
            if raw_name.lower() != normalized_name.lower():
                if not Store.objects.filter(name__iexact=raw_name).exists():
                    store = Store.objects.create(name=raw_name, preferred=preferred_store)
                    logger.info(f"[get_or_create_store] Created variant store '{raw_name}' → preferred '{normalized_name}'")
                    return store

            return preferred_store

    except Exception:
        logger.exception(f"[get_or_create_store] Error creating store for '{raw_name}'")
        return None


# ============================================================
# PRODUCTS
# ============================================================
def get_or_create_product_name(
    raw_name: str,
    normalized_name: str | None = None,
    brand_ref=None,
    unit_ref=None,
    category=None
) -> Product | None:
    """
    Find or create a Product using both raw and normalized names.
    """
    if not raw_name and not normalized_name:
        logger.warning("[get_or_create_product_name] Missing both raw_name and normalized_name → returning None")
        return None

    normalized_name = normalized_name or raw_name

    try:
        # 1️⃣ Find by raw name
        product = Product.objects.filter(name__iexact=raw_name).first()
        if product:
            logger.debug(f"[get_or_create_product_name] Found existing product '{raw_name}' (id={product.id})")
            return product

        # 2️⃣ Create or reuse preferred product
        preferred_product = Product.objects.filter(name__iexact=normalized_name).first()
        if not preferred_product:
            preferred_product = Product.objects.create(
                name=normalized_name,
                preferred_unit=unit_ref,
                category=category,
            )
            logger.info(f"[get_or_create_product_name] Created new preferred product '{normalized_name}' (id={preferred_product.id})")

        # 3️⃣ Create variant if raw_name differs
        if raw_name.lower() != normalized_name.lower():
            product = Product.objects.create(
                name=raw_name,
                preferred=preferred_product,
                brand=brand_ref,
            )
            logger.info(f"[get_or_create_product_name] Created variant product '{raw_name}' → preferred '{normalized_name}'")
            return product

        return preferred_product

    except Exception as e:
        logger.warning(f"[get_or_create_product_name] Error creating product for '{raw_name}' → {e}", exc_info=True)
        return None


# ============================================================
# BRANDS
# ============================================================
def get_or_create_brand(raw_name: str, normalized_name: str | None = None) -> Brand | None:
    """
    Find or create a Brand using both raw and normalized names.
    """
    if not raw_name and not normalized_name:
        logger.warning("[get_or_create_brand] Missing both raw_name and normalized_name → returning None")
        return None

    normalized_name = normalized_name or raw_name

    try:
        # 1️⃣ Try to find existing brand with raw name
        brand = Brand.objects.filter(name__iexact=raw_name).first()
        if brand:
            logger.debug(f"[get_or_create_brand] Found existing brand '{raw_name}' (id={brand.id})")
            return brand

        # 2️⃣ Create or reuse preferred brand
        preferred_brand = Brand.objects.filter(name__iexact=normalized_name).first()
        if not preferred_brand:
            preferred_brand = Brand.objects.create(name=normalized_name)
            logger.info(f"[get_or_create_brand] Created new preferred brand '{normalized_name}' (id={preferred_brand.id})")

        # 3️⃣ Create variant if names differ
        if raw_name.lower() != normalized_name.lower():
            brand = Brand.objects.create(name=raw_name, preferred=preferred_brand)
            logger.info(f"[get_or_create_brand] Created variant brand '{raw_name}' → preferred '{normalized_name}'")
            return brand

        return preferred_brand

    except Exception as e:
        logger.warning(f"[get_or_create_brand] Error creating brand for '{raw_name}' → {e}", exc_info=True)
        return None
