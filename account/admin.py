# account/admin.py
from django.contrib import admin
from django.core.paginator import Paginator

from user.admin import RestrictedAdmin
from .models import AccountType, Account
from django_admin_listfilter_dropdown.filters import RelatedOnlyDropdownFilter

@admin.register(AccountType)
class AccountTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "group",)
    list_filter = ("group",)
    search_fields = ("name", "code", "group", "description")
    ordering = ("group", "name")
    readonly_fields = ("created_at", "modified_at")


@admin.register(Account)
class AccountAdmin(RestrictedAdmin):
    list_display = ("name", "account_type", "institution", "balance_with_currency", "is_active", "created_at")
    list_filter = ("account_type__group", "is_active", ("currency", RelatedOnlyDropdownFilter), ("created_by", RelatedOnlyDropdownFilter))
    search_fields = ("name", "institution__name", "account_type__name", "created_by__email", "created_by__first_name", "created_by__last_name")
    autocomplete_fields = ("account_type", "institution", "currency")
    ordering = ("name",)
    readonly_fields = ("created_at", "modified_at")
    change_form_template = "admin/account/account/change_form.html"
    
    def get_queryset(self, request):
        """Optimize query by prefetching related transactions."""
        qs = super().get_queryset(request)
        return qs.prefetch_related(
            'transactions__currency',
            'transactions__store',
            'transactions__category'
        )

    def balance_with_currency(self, obj):
        """Display computed balance + currency symbol/code."""
        balance = obj.computed_balance
        currency = obj.currency.code if obj.currency else "—"
        return f"{balance:.2f} {currency}"

    balance_with_currency.short_description = "Balance"
    
    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        """Add ordered and paginated transactions to the context."""
        extra_context = extra_context or {}
        if object_id:
            try:
                account = self.get_object(request, object_id)
                if account:
                    # Get transactions ordered by date (newest first)
                    transactions = account.transactions.select_related(
                        'currency', 'store', 'category'
                    ).order_by('-date')
                    
                    # Get total count before pagination
                    total_count = transactions.count()
                    
                    # Paginate transactions (25 per page)
                    paginator = Paginator(transactions, 25)
                    page_number = request.GET.get('transactions_page', 1)
                    try:
                        page_number = int(page_number)
                    except (ValueError, TypeError):
                        page_number = 1
                    
                    try:
                        transactions_page = paginator.page(page_number)
                    except Exception:
                        transactions_page = paginator.page(1)
                    
                    # Calculate page range (show max 10 pages around current)
                    num_pages = paginator.num_pages
                    current_page = transactions_page.number
                    if num_pages <= 10:
                        page_range = paginator.page_range
                    else:
                        # Show pages around current page
                        start = max(1, current_page - 4)
                        end = min(num_pages, current_page + 5)
                        if end - start < 9:
                            if start == 1:
                                end = min(num_pages, start + 9)
                            else:
                                start = max(1, end - 9)
                        page_range = range(start, end + 1)
                    
                    extra_context['account_transactions'] = transactions_page
                    extra_context['transactions_paginator'] = paginator
                    extra_context['transactions_total_count'] = total_count
                    extra_context['transactions_page_range'] = page_range
            except Exception:
                pass
        return super().changeform_view(request, object_id, form_url, extra_context)
