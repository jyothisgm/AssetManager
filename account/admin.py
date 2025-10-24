# account/admin.py
from django.contrib import admin

from user.admin import RestrictedAdmin
from .models import AccountType, Account

@admin.register(AccountType)
class AccountTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "group",)
    list_filter = ("group",)
    search_fields = ("name", "code", "description")
    ordering = ("group", "name")

    readonly_fields = ("created_at", "modified_at")


@admin.register(Account)
class AccountAdmin(RestrictedAdmin):
    list_display = ("name", "account_type", "institution", "balance_with_currency", "is_active", "created_at")
    list_filter = ("account_type__group", "is_active", "currency")
    search_fields = ("name", "institution__name", "account_type__name")
    autocomplete_fields = ("account_type", "institution", "currency")
    ordering = ("name",)
    readonly_fields = ("created_at", "modified_at")

    def balance_with_currency(self, obj):
        """Display computed balance + currency symbol/code."""
        balance = obj.computed_balance
        currency = obj.currency.code if obj.currency else "—"
        return f"{balance:.2f} {currency}"
    balance_with_currency.short_description = "Balance"
