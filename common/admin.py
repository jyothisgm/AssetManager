from django.contrib import admin
from common.models import Currency, Unit
from common.logging_config import logger, raise_with_line_info


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
    list_filter = ("category",)
    search_fields = ("name", "symbol")
    readonly_fields = ("created_at", "modified_at")

    def preferred_display(self, obj):
        return obj.preferred.name if obj.preferred else "-"
    preferred_display.short_description = "Preferred Unit"

    def base_unit_display(self, obj):
        return obj.base_unit.name if obj.base_unit else "-"
    base_unit_display.short_description = "Base Unit"

    def variant_count(self, obj):
        return obj.variants.count()


# ------------------------------
# CURRENCY ADMIN
# ------------------------------
@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name", "symbol", "country")
    list_filter = ("type", "is_active", "is_base_currency", "country")
    ordering = ("type", "code")

    def get_queryset(self, request):
        func_name = f"{self.__class__.__name__}.get_queryset"
        try:
            logger.debug(f"[{func_name}] Fetching queryset for CurrencyAdmin")
            qs = super().get_queryset(request)
            qs = qs.select_related(None)  # keep it lightweight
            logger.debug(f"[{func_name}] Retrieved {qs.count()} currency records")
            return qs
        except Exception as e:
            logger.exception(f"[{func_name}] Error retrieving currency queryset")
            raise_with_line_info(func_name, e)
