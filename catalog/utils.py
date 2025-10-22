from catalog.models import Brand, Product, Store


def get_or_create_store(raw_name: str, normalized_name: str | None = None) -> Store | None:
    """Find or create a Store using both raw and normalized names.
    - First, try to find store by raw_name.
    - If not found, find or create preferred store using normalized_name.
    - Create variant (raw) if it differs from preferred.
    """
    if not raw_name and not normalized_name:
        return None

    normalized_name = normalized_name or raw_name

    # 1️⃣ Try to find existing store with the raw name
    store = Store.objects.filter(name__iexact=raw_name).first()
    if store:
        return store

    # 2️⃣ Find or create the preferred store using normalized_name
    preferred_store = Store.objects.filter(name__iexact=normalized_name).first()
    if not preferred_store:
        preferred_store = Store.objects.create(name=normalized_name)

    # 3️⃣ If raw_name differs, create a variant linked to the preferred one
    if raw_name.lower() != normalized_name.lower():
        store = Store.objects.create(name=raw_name, preferred=preferred_store)
        # Optional: maintain reverse link consistency
        preferred_store.variants.add(store)
        return store

    # 4️⃣ If same name, just return the preferred
    return preferred_store


def get_or_create_product_name(raw_name: str, normalized_name: str | None = None, brand_ref=None, unit_ref=None, category=None) -> Product | None:
    """Find or create an Product using both raw and normalized names."""
    if not raw_name and not normalized_name:
        return None

    normalized_name = normalized_name or raw_name

    # 1️⃣ Try to find existing store with the raw name
    product = Product.objects.filter(name__iexact=raw_name).first()
    if product:
        return product

    # 2️⃣ Find or create the preferred store using normalized_name
    preferred_product = Product.objects.filter(name__iexact=normalized_name).first()
    if not preferred_product:
        preferred_product = Product.objects.create(name=normalized_name, preferred_unit=unit_ref, category=category)

    # 3️⃣ If raw_name differs, create a variant linked to the preferred one
    if raw_name.lower() != normalized_name.lower():
        product = Product.objects.create(name=raw_name, preferred=preferred_product, brand=brand_ref)
        # Optional: maintain reverse link consistency
        preferred_product.variants.add(product)
        return product

    # 4️⃣ If same name, just return the preferred
    return preferred_product


def get_or_create_brand(raw_name: str, normalized_name: str | None = None) -> Brand | None:
    """Find or create a Brand using both raw and normalized names.
    - Try to find an existing brand by raw_name.
    - If not found, find or create a preferred brand using normalized_name.
    - If names differ, create a variant brand linked to the preferred one.
    """
    if not raw_name and not normalized_name:
        return None

    normalized_name = normalized_name or raw_name

    # 1️⃣ Try to find existing brand with the raw name
    brand = Brand.objects.filter(name__iexact=raw_name).first()
    if brand:
        return brand

    # 2️⃣ Find or create the preferred brand using normalized_name
    preferred_brand = Brand.objects.filter(name__iexact=normalized_name).first()
    if not preferred_brand:
        preferred_brand = Brand.objects.create(name=normalized_name)

    # 3️⃣ If raw_name differs, create a variant linked to the preferred one
    if raw_name.lower() != normalized_name.lower():
        brand = Brand.objects.create(name=raw_name, preferred=preferred_brand)
        # Optional: maintain reverse link consistency
        preferred_brand.variants.add(brand)
        return brand

    # 4️⃣ If same name, just return the preferred
    return preferred_brand
