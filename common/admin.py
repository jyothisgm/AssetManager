from django.contrib import admin
from common.models import Currency, Unit
from common.logging_config import logger
from django_admin_listfilter_dropdown.filters import DropdownFilter, RelatedOnlyDropdownFilter

# ------------------------------
# UNIT ADMIN
# ------------------------------
@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "symbol",
        "category",
        "preferred_display",
        "base_unit_display",
        "conversion_to_base",
        "variant_count",
        "created_at",
    )
    search_fields = (
        "name",
        "symbol",
        "preferred__name",
        "preferred__symbol",
        "base_unit__name",
        "base_unit__symbol",
    )
    list_filter = (
        "category", 
        ("base_unit", RelatedOnlyDropdownFilter),
        ("preferred", RelatedOnlyDropdownFilter)
    )
    autocomplete_fields = ('preferred', 'base_unit')
    readonly_fields = ("created_at", "modified_at")

    def preferred_display(self, obj):
        return obj.preferred.name if obj.preferred else "-"
    preferred_display.short_description = "Preferred Unit"

    def base_unit_display(self, obj):
        return obj.base_unit.name if obj.base_unit else "-"
    base_unit_display.short_description = "Base Unit"

    def variant_count(self, obj):
        return obj.variants.count()
    
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "preferred":
            # exclude the current store itself and deleted ones
            qs = Unit.objects.filter(is_deleted=False, preferred=None)
            if request.resolver_match.kwargs.get("object_id"):
                current_id = request.resolver_match.kwargs["object_id"]
                qs = qs.exclude(id=current_id)
            kwargs["queryset"] = qs.order_by("name")
        if db_field.name == "base_unit":
            # exclude the current store itself and deleted ones
            qs = Unit.objects.filter(is_deleted=False, base_unit=None)
            if request.resolver_match.kwargs.get("object_id"):
                current_id = request.resolver_match.kwargs["object_id"]
                qs = qs.exclude(id=current_id)
            kwargs["queryset"] = qs.order_by("name")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_search_results(self, request, queryset, search_term):
        queryset, may_have_duplicates = super().get_search_results(request, queryset, search_term)

        # This path is used by the admin's autocomplete endpoint
        if request.path.endswith("/autocomplete/"):
            # Only restrict when the requesting field is Product.preferred_unit
            if request.GET.get("field_name") == "preferred_unit" and \
                request.GET.get("app_label") == "catalog" and \
                request.GET.get("model_name") == "product":
                queryset = queryset.filter(preferred=None)

        return queryset, may_have_duplicates



# ------------------------------
# CURRENCY ADMIN
# ------------------------------
@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "symbol", "country", "type")
    search_fields = ("code", "name", "symbol", "country")
    list_filter = ("type", ("country", DropdownFilter))
    ordering = ("type", "code")

    def get_queryset(self, request):
        func_name = f"{self.__class__.__name__}.get_queryset"
        try:
            qs = super().get_queryset(request)
            qs = qs.select_related(None)  # keep it lightweight
            return qs
        except Exception as e:
            logger.exception(f"[{func_name}] Error retrieving currency queryset")
            raise e
