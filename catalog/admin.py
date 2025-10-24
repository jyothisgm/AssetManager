from django.contrib import admin

from catalog.models import CategoryGroup, ExchangeRateRecord, Institution, Product, PurchaseCategory, Brand, Store
from user.admin import RestrictedAdmin, RestrictedViewAdmin

# Register your models here.
@admin.register(CategoryGroup)
class CategoryGroupAdmin(RestrictedViewAdmin):
    list_display = ("name", "category_count", "created_at", "modified_at")
    search_fields = ("name",)

    def category_count(self, obj):
        return obj.categories.count()
    category_count.short_description = "No. of Categories"


@admin.register(PurchaseCategory)
class PurchaseCategoryAdmin(RestrictedViewAdmin):
    list_display = (
        "name",
        "group",
        "created_at",
        "modified_at",
    )
    search_fields = ("name",)
    list_filter = ("group",)


@admin.register(Brand)
class BrandAdmin(RestrictedViewAdmin):
    list_display = ("name", "preferred", "created_at")
    search_fields = ("name",)
    ordering = ("name",)

@admin.register(Store)
class StoreAdmin(RestrictedViewAdmin):
    list_display = ("name", "preferred_name", "category_names", "variant_count", "created_at", "modified_at", 'created_by')
    search_fields = ("name",)

    def preferred_name(self, obj):
        return obj.preferred.name if obj.preferred else "-"
    preferred_name.short_description = "Preferred"

    def category_names(self, obj):
        # join all category names, or show "-" if none
        cats = obj.categories.all()
        if not cats.exists():
            return "-"
        return ", ".join(c.name for c in cats)
    category_names.short_description = "Categories"

    def variant_count(self, obj):
        return obj.variants.count()
    variant_count.short_description = "No. of Variants"


# ------------------------------
# ITEM NAME ADMIN
# ------------------------------
@admin.register(Product)
class ProductAdmin(RestrictedViewAdmin):
    list_display = (
        "name",
        "preferred_display",
        "brand_display",
        "preferred_unit_display",
        "variant_count",
        "created_at",
        "modified_at",
    )
    search_fields = ("name", "brand__name")
    list_filter = ("preferred_unit", "brand")
    autocomplete_fields = ("preferred", "brand", "preferred_unit")
    ordering = ("name",)

    # --- Display helpers ---
    def preferred_display(self, obj):
        """Show canonical item name (preferred variant)"""
        if obj.preferred:
            return obj.preferred.name
        return "–"
    preferred_display.short_description = "Canonical Item"

    def brand_display(self, obj):
        """Show associated brand name"""
        if obj.brand:
            return obj.brand.name
        return "–"
    brand_display.short_description = "Brand"

    def preferred_unit_display(self, obj):
        """Show the preferred or inherited unit"""
        unit = obj.get_preferred_unit()
        if unit:
            return f"{unit.name}"
        return "–"
    preferred_unit_display.short_description = "Preferred Unit"

    def variant_count(self, obj):
        """Number of variants for this canonical item"""
        return obj.variants.count()
    variant_count.short_description = "Variants"

    # --- Add link to variants ---
    def get_queryset(self, request):
        """Optimize queryset for performance"""
        qs = super().get_queryset(request)
        return qs.select_related("preferred", "brand", "preferred_unit").prefetch_related("variants")

# ------------------------------
# INSTITUTION ADMIN
# ------------------------------
@admin.register(Institution)
class InstitutionAdmin(RestrictedViewAdmin):
    list_display = (
        "name",
        "short_name",
        "type",
        "country",
        "preferred_display",
        "website",
        "created_at",
    )
    search_fields = ("name", "short_name")
    list_filter = ("type", "country")
    ordering = ("name",)
    autocomplete_fields = ("preferred",)

    def preferred_display(self, obj):
        return obj.preferred.name if obj.preferred else "-"
    preferred_display.short_description = "Canonical Institution"

# ------------------------------
# EXCHANGE RATE RECORD ADMIN
# ------------------------------
@admin.register(ExchangeRateRecord)
class ExchangeRateRecordAdmin(RestrictedAdmin):
    list_display = (
        "date",
        "currency_exchange_display",
        "provider",
        "provider_rate",
        "market_rate",
        "fee_percent",
    )
    search_fields = (
        "base_currency__code",
        "quote_currency__code",
        "provider__name",
    )
    list_filter = ("provider", "base_currency", "quote_currency")
    ordering = ("date",)
    autocomplete_fields = ("base_currency", "quote_currency", "provider")

    def currency_exchange_display(self, obj):
        return obj.base_currency.code + "-" + obj.quote_currency.code
    currency_exchange_display.short_description = "Currency Exchange"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("base_currency", "quote_currency", "provider")
