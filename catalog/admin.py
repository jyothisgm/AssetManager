from django.contrib import admin
from django.utils.html import format_html

from catalog.models import CategoryGroup, ExchangeRateRecord, Institution, Product, PurchaseCategory, Brand, Store
from user.admin import RestrictedAdmin, RestrictedViewAdmin
from django_admin_listfilter_dropdown.filters import RelatedOnlyDropdownFilter, RelatedDropdownFilter
from common.logging_config import logger

# Register your models here.
@admin.register(Brand)
class BrandAdmin(RestrictedViewAdmin):
    list_display = ("name", "preferred", "created_at")
    search_fields = ("name", "preferred__name")
    ordering = ("name",)
    list_filter = (
        ("preferred", RelatedOnlyDropdownFilter),
    )
    autocomplete_fields = ("preferred",)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "preferred":
            # exclude the current store itself and deleted ones
            qs = Brand.objects.filter(is_deleted=False, preferred=None)
            if request.resolver_match.kwargs.get("object_id"):
                current_id = request.resolver_match.kwargs["object_id"]
                qs = qs.exclude(id=current_id)
            kwargs["queryset"] = qs.order_by("name")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(CategoryGroup)
class CategoryGroupAdmin(RestrictedViewAdmin):
    list_display = ("name", "category_count")
    search_fields = ("name", "description")

    def category_count(self, obj):
        return obj.categories.count()
    category_count.short_description = "No. of Categories"


@admin.register(PurchaseCategory)
class PurchaseCategoryAdmin(RestrictedViewAdmin):
    list_display = (
        "name",
        "group",
    )
    search_fields = ("name", "description", "group__name")
    list_filter = ("group",)
    autocomplete_fields = ("group",)


@admin.register(Store)
class StoreAdmin(RestrictedViewAdmin):
    list_display = ("name", "preferred", "category_names", "variant_count", "modified_at")
    search_fields = ("name", "preferred__name", "categories__name", "created_by__email", "created_by__first_name", "created_by__last_name")
    autocomplete_fields = ("preferred", "categories")
    list_filter = (
        ("preferred", RelatedOnlyDropdownFilter),
        ("categories", RelatedOnlyDropdownFilter),
    )

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
    
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "preferred":
            # exclude the current store itself and deleted ones
            qs = Store.objects.filter(is_deleted=False, preferred=None)
            if request.resolver_match.kwargs.get("object_id"):
                current_id = request.resolver_match.kwargs["object_id"]
                qs = qs.exclude(id=current_id)
            kwargs["queryset"] = qs.order_by("name")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


# ------------------------------
# ITEM NAME ADMIN
# ------------------------------
@admin.register(Product)
class ProductAdmin(RestrictedViewAdmin):
    list_display = (
        "name",
        "preferred",
        "brand_display",
        "category",
        "preferred_unit_display",
        "variant_count",
    )
    search_fields = ("name", "brand__name", "preferred__name", "category__group__name", "category__name")
    list_filter = (
        ("brand", RelatedOnlyDropdownFilter), 
        ("preferred", RelatedOnlyDropdownFilter),
        ("category", RelatedOnlyDropdownFilter),
    )
    autocomplete_fields = ("preferred", "brand", "preferred_unit", "category")
    ordering = ("name",)

    # --- Display helpers ---
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

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "preferred":
            # exclude the current store itself and deleted ones
            qs = Product.objects.filter(is_deleted=False, preferred=None)
            if request.resolver_match.kwargs.get("object_id"):
                current_id = request.resolver_match.kwargs["object_id"]
                qs = qs.exclude(id=current_id)
            kwargs["queryset"] = qs.order_by("name")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


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
    search_fields = ("name",
        "short_name",
        "type",
        "country",
        "preferred__name",
        "website",
    )
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
    list_filter = (
        ("provider", RelatedOnlyDropdownFilter),
        ("base_currency", RelatedOnlyDropdownFilter),
        ("quote_currency", RelatedOnlyDropdownFilter),
    )
    ordering = ("-date",)
    autocomplete_fields = ("base_currency", "quote_currency", "provider")

    def currency_exchange_display(self, obj):
        """Show exchange pair like USD → EUR."""
        try:
            return format_html(
                "{} → {}",
                obj.base_currency.code if obj.base_currency else "—",
                obj.quote_currency.code if obj.quote_currency else "—",
            )
        except Exception as e:
            logger.warning(
                f"[ExchangeRateRecordAdmin.currency_exchange_display] Error rendering exchange pair: {e}"
            )
            return "—"

    currency_exchange_display.short_description = "Currency Exchange"

    def get_queryset(self, request):
        """Optimize related queries."""
        qs = super().get_queryset(request)
        return qs.select_related("base_currency", "quote_currency", "provider")
