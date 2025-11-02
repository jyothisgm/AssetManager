from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.utils.html import format_html

from catalog.forms import BulkEditBrandForm, BulkEditProductForm, BulkEditStoreForm
from catalog.models import CategoryGroup, ExchangeRateRecord, Institution, Product, PurchaseCategory, Brand, Store
from common.models import Unit
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
    actions = ["bulk_edit_brands"]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "preferred":
            # exclude the current store itself and deleted ones
            qs = Brand.objects.filter(is_deleted=False, preferred=None)
            if request.resolver_match.kwargs.get("object_id"):
                current_id = request.resolver_match.kwargs["object_id"]
                qs = qs.exclude(id=current_id)
            kwargs["queryset"] = qs.order_by("name")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def bulk_edit_brands(self, request, queryset):
        """Bulk edit selected brands."""
        queryset = queryset.filter(created_by=request.user)
        if not queryset.exists():
            self.message_user(request, "You can only edit objects you created.", level="error")
            return redirect(request.get_full_path())
        if "apply" in request.POST:
            form = BulkEditBrandForm(request.POST, request=request)
            if form.is_valid():
                preferred = form.cleaned_data.get("preferred")
                count = queryset.update(preferred=preferred)
                messages.success(request, f"✅ Updated preferred brand for {count} brand(s).")
                return redirect(request.get_full_path())
        else:
            form_initial = {}
            if queryset.exists():
                values = list(set(queryset.values_list("preferred", flat=True)))
                if len(values) == 1:
                    form_initial["preferred"] = values[0]
            form = BulkEditBrandForm(request=request, initial=form_initial)

        context = dict(
            self.admin_site.each_context(request),
            title="Bulk Edit Brands",
            queryset=queryset,
            form=form,
            opts=self.model._meta,
        )
        return render(request, "admin/bulk_edit_brands.html", context)
    bulk_edit_brands.short_description = "Edit selected brands"


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
    actions = ["bulk_edit_stores"]

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

    def bulk_edit_stores(self, request, queryset):
        """Bulk edit selected stores."""
        queryset = queryset.filter(created_by=request.user)
        if not queryset.exists():
            self.message_user(request, "You can only edit objects you created.", level="error")
            return redirect(request.get_full_path())
        if "apply" in request.POST:
            form = BulkEditStoreForm(request.POST, request=request)
            if form.is_valid():
                data = {k: v for k, v in form.cleaned_data.items() if v not in (None, "", [])}
                count = 0
                for obj in queryset:
                    if "preferred" in data:
                        obj.preferred = data["preferred"]
                    if "categories" in data:
                        obj.categories.set(data["categories"])
                    obj.save()
                    count += 1
                messages.success(request, f"✅ Updated {count} store(s) successfully.")
                return redirect(request.get_full_path())
        else:
            form_initial = {}
            if queryset.exists():
                for field_name in ["preferred"]:
                    unique = list(set(queryset.values_list(field_name, flat=True)))
                    if len(unique) == 1:
                        form_initial[field_name] = unique[0]
            form = BulkEditStoreForm(request=request, initial=form_initial)
        context = dict(
            self.admin_site.each_context(request),
            title="Bulk Edit Stores",
            queryset=queryset,
            form=form,
            opts=self.model._meta,
        )

        return render(request, "admin/bulk_edit_stores.html", context)
    bulk_edit_stores.short_description = "Edit selected stores"


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
    actions = ["bulk_edit_products"]

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
        if db_field.name == "preferred_unit":
            kwargs["queryset"] = Unit.objects.filter(preferred=None)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def bulk_edit_products(self, request, queryset):
        """Bulk edit selected products."""
        queryset = queryset.filter(created_by=request.user)
        if not queryset.exists():
            self.message_user(request, "You can only edit objects you created.", level="error")
            return redirect(request.get_full_path())

        if "apply" in request.POST:
            form = BulkEditProductForm(request.POST, request=request)
            if form.is_valid():
                data = {k: v for k, v in form.cleaned_data.items() if v not in (None, "", [])}
                count = 0
                for obj in queryset:
                    for field, value in data.items():
                        setattr(obj, field, value)
                    obj.save()
                    count += 1
                messages.success(request, f"✅ Updated {count} product(s) successfully.")
                return redirect(request.get_full_path())
        else:
            form_initial = {}
            if queryset.exists():
                for field_name in ["preferred", "brand", "preferred_unit", "category"]:
                    unique = list(set(queryset.values_list(field_name, flat=True)))
                    if len(unique) == 1:
                        form_initial[field_name] = unique[0]
            form = BulkEditProductForm(request=request, initial=form_initial)

        context = dict(
            self.admin_site.each_context(request),
            title="Bulk Edit Products",
            queryset=queryset,
            form=form,
            opts=self.model._meta,
        )
        return render(request, "admin/bulk_edit_products.html", context)
    bulk_edit_products.short_description = "Edit selected products"

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
