from decimal import Decimal, InvalidOperation
import mimetypes
import os
import uuid
import pytz
from datetime import timedelta, date
from collections import defaultdict

from django import forms
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.shortcuts import render, redirect
from django.db.models import Sum, Case, When, F, Q, DecimalField, Value, ExpressionWrapper
from django.urls import path
from django.utils import timezone
from django.utils.html import format_html
from rangefilter.filters import DateRangeFilter
from django.contrib.contenttypes.models import ContentType
from django.template.response import TemplateResponse
from django.http import JsonResponse

from account.models import Account
from catalog.exchange_rate import fetch_market_rate
from catalog.models import ExchangeRateRecord, Institution, PurchaseCategory, Store
from common.models import Unit
from transaction.admin_forms import BulkEditTransactionForm, TransactionForm, TransactionItemInlineForm, TransactionSplitFormSet
from transaction.models import Transaction, TransactionItem, TransactionSplit, OwesDummyModel
from transaction.invoice_handling import process_transaction_file
from user.admin import RestrictedAdmin
from django_admin_listfilter_dropdown.filters import RelatedOnlyDropdownFilter, DropdownFilter
from django.db.models.functions import Coalesce
from django.db import transaction as db_transaction

from common.logging_config import logger
from user.models import Attachment, get_attachment_type

from transaction.admin_forms import BulkEditTransactionItemForm  # safe import here


# -----------------------------------
# TRANSACTION SPLIT ADMIN
# -----------------------------------
@admin.register(TransactionSplit)
class TransactionSplitAdmin(RestrictedAdmin):
    """Admin for TransactionSplit - allows direct deletion of splits."""
    list_display = ('transaction', 'user', 'amount', 'created_at')
    list_filter = ('created_at', ('transaction', RelatedOnlyDropdownFilter), ('user', RelatedOnlyDropdownFilter))
    search_fields = ('transaction__description', 'user__email')
    readonly_fields = ('id', 'created_at', 'modified_at', 'created_by')
    
    def has_add_permission(self, request):
        """Disable adding splits directly - they should be added via Transaction inline."""
        return False
    
    def has_change_permission(self, request, obj=None):
        """Disable editing splits directly - they should be edited via Transaction inline."""
        return False


def _render_owes_view(request, admin_site, model_opts):
    """Shared function to render the owes view - shows merged net balances with all users."""
    
    User = get_user_model()
    current_user = request.user
    
    # ============================================
    # PART 1: Who the current user owes money to
    # ============================================
    # Get all splits where the current user owes money (user = current_user)
    user_owes_splits = TransactionSplit.objects.filter(
        user=current_user,
        is_deleted=False
    ).select_related('transaction', 'transaction__currency', 'transaction__account', 'transaction__created_by')
    
    # Group by owed_to user (transaction creator) and currency
    # Structure: {owed_to_user: {currency: total_amount}}
    owes_data = defaultdict(lambda: defaultdict(Decimal))
    owes_details = defaultdict(lambda: defaultdict(list))
    
    for split in user_owes_splits:
        # Get who the current user owes to (transaction creator)
        owed_to_user = None
        if split.transaction and split.transaction.created_by:
            owed_to_user = split.transaction.created_by
        
        if not owed_to_user:
            continue
        
        # Get currency from transaction or account
        currency = None
        currency_symbol = ""
        if split.transaction:
            currency = split.transaction.currency
            if not currency and split.transaction.account:
                currency = split.transaction.account.currency
            
            if currency:
                currency_symbol = getattr(currency, 'symbol', None) or getattr(currency, 'code', '')
        
        currency_key = currency_symbol or 'Unknown'
        owes_data[owed_to_user][currency_key] += Decimal(str(split.amount))
        owes_details[owed_to_user][currency_key].append({
            'transaction': split.transaction,
            'amount': split.amount,
            'date': split.transaction.date if split.transaction else None,
        })
    
    # ============================================
    # PART 2: Who owes money to the current user
    # ============================================
    # Get all splits where the current user is the transaction creator (gets money from others)
    owed_by_splits = TransactionSplit.objects.filter(
        transaction__created_by=current_user,
        is_deleted=False
    ).select_related('user', 'transaction', 'transaction__currency', 'transaction__account')
    
    # Group by user who owes (split.user) and currency
    # Structure: {owed_by_user: {currency: total_amount}}
    owed_by_data = defaultdict(lambda: defaultdict(Decimal))
    owed_by_details = defaultdict(lambda: defaultdict(list))
    
    for split in owed_by_splits:
        # Get who owes money to the current user (split.user)
        owed_by_user = split.user
        if not owed_by_user:
            continue
        
        # Get currency from transaction or account
        currency = None
        currency_symbol = ""
        if split.transaction:
            currency = split.transaction.currency
            if not currency and split.transaction.account:
                currency = split.transaction.account.currency
            
            if currency:
                currency_symbol = getattr(currency, 'symbol', None) or getattr(currency, 'code', '')
        
        currency_key = currency_symbol or 'Unknown'
        owed_by_data[owed_by_user][currency_key] += Decimal(str(split.amount))
        owed_by_details[owed_by_user][currency_key].append({
            'transaction': split.transaction,
            'amount': split.amount,
            'date': split.transaction.date if split.transaction else None,
        })
    
    # ============================================
    # PART 3: Merge both sides and calculate net balance
    # ============================================
    # Combine all users from both sides
    all_users = set()
    all_users.update(owes_data.keys())
    all_users.update(owed_by_data.keys())
    
    # Calculate net balance for each user and currency
    # Negative = current user owes them, Positive = they owe current user
    merged_data = []
    
    for user in all_users:
        # Get what current user owes to this user (negative)
        owes_to_this_user = owes_data.get(user, {})
        owes_to_details = owes_details.get(user, {})
        
        # Get what this user owes to current user (positive)
        this_user_owes = owed_by_data.get(user, {})
        this_user_owes_details = owed_by_details.get(user, {})
        
        # Calculate net balance per currency
        # net = (what they owe you) - (what you owe them)
        # positive = they owe you, negative = you owe them
        net_currency_totals = defaultdict(Decimal)
        net_currency_details = defaultdict(lambda: {'owed_to': [], 'owed_by': []})
        
        # Process all currencies from both sides
        all_currencies = set()
        all_currencies.update(owes_to_this_user.keys())
        all_currencies.update(this_user_owes.keys())
        
        for currency_key in all_currencies:
            owed_to_amount = owes_to_this_user.get(currency_key, Decimal('0'))
            owed_by_amount = this_user_owes.get(currency_key, Decimal('0'))
            
            # Net = what they owe you - what you owe them
            net_amount = owed_by_amount - owed_to_amount
            net_currency_totals[currency_key] = net_amount
            
            # Store details for both sides
            if currency_key in owes_to_details:
                net_currency_details[currency_key]['owed_to'] = owes_to_details[currency_key]
            if currency_key in this_user_owes_details:
                net_currency_details[currency_key]['owed_by'] = this_user_owes_details[currency_key]
        
        # Calculate total net amount across all currencies
        total_net_amount = sum(net_currency_totals.values())
        
        # Only include if there's a non-zero balance
        if total_net_amount != 0 or any(net_currency_totals.values()):
            merged_data.append({
                'user': user,
                'net_currency_totals': dict(net_currency_totals),
                'net_currency_details': dict(net_currency_details),
                'total_net_amount': total_net_amount,
                'owed_to_totals': dict(owes_to_this_user),
                'owed_by_totals': dict(this_user_owes),
            })
    
    # Sort by absolute net amount, highest first
    merged_data.sort(
        key=lambda x: abs(x['total_net_amount']),
        reverse=True
    )
    
    context = dict(
        admin_site.each_context(request),
        title=f"Owes Summary - {current_user.email}",
        merged_data=merged_data,
        current_user=current_user,
        opts=model_opts,
    )
    
    return render(request, "admin/transaction/owes.html", context)


def _D(val):
    """Safe Decimal: None/'' -> 0"""
    try:
        if val is None or val == "":
            return Decimal("0")
        return Decimal(val)
    except Exception:
        return Decimal("0")


def create_fee_transaction(parent_transaction, fee_amount, user, currency=None, store=None):
    """
    Creates a fee transaction linked to a parent transaction.
    
    Args:
        parent_transaction: The Transaction object that the fee is associated with
        fee_amount: The fee amount (Decimal or float)
        user: The user who created the parent transaction
        currency: Optional Currency object (defaults to parent's currency)
        store: Optional Store object for the fee (defaults to "Conversion Fees" or "Bank Fee")
    
    Returns:
        Transaction: The created fee transaction, or None if fee_amount is invalid
    """
    func_name = "create_fee_transaction"
    try:
        if not fee_amount or fee_amount <= 0:
            return None
        
        fee_amount = Decimal(str(fee_amount))
        currency = currency or parent_transaction.currency
        
        # Get or create Bank Fee category
        bank_fee_category = PurchaseCategory.objects.filter(name__iexact="Bank Fee").first()
        if not bank_fee_category:
            bank_fee_category, _ = PurchaseCategory.objects.get_or_create(
                name="Bank Fee",
                defaults={"created_by": user}
            )
        
        # Get or create Conversion Fees store
        if not store:
            conversion_store = Store.objects.filter(name__iexact="Conversion Fees").first()
            if not conversion_store:
                conversion_store, _ = Store.objects.get_or_create(
                    name="Conversion Fees",
                    defaults={"created_by": user, "category": bank_fee_category}
                )
            store = conversion_store
        
        # Check if fee transaction already exists
        existing_fee = parent_transaction.fee
        if existing_fee:
            # Update existing fee transaction
            existing_fee.amount = fee_amount
            existing_fee.currency = currency
            existing_fee.category = bank_fee_category
            existing_fee.store = store
            existing_fee.date = parent_transaction.date
            existing_fee.account = parent_transaction.account
            existing_fee.description = f"Fee for transaction {parent_transaction.id}"
            existing_fee.save()
            logger.info(f"[{func_name}] Updated fee transaction {existing_fee.id} for {parent_transaction.id}")
            return existing_fee
        
        # Create new fee transaction
        fee_tx = Transaction.objects.create(
            created_by=user,
            account=parent_transaction.account,
            transaction_type="debit",
            amount=fee_amount,
            date=parent_transaction.date,
            currency=currency,
            category=bank_fee_category,
            store=store,
            description=f"Fee for transaction {parent_transaction.id}",
            notes="auto-imported fee",
        )
        
        # Link fee to parent transaction
        parent_transaction.fee = fee_tx
        parent_transaction.save(update_fields=["fee"])
        
        logger.info(f"[{func_name}] Created fee transaction {fee_tx.id} (amount={fee_amount}) for {parent_transaction.id}")
        return fee_tx
        
    except Exception as e:
        logger.warning(f"[{func_name}] Error creating fee transaction: {e}", exc_info=True)
        return None

class ProductCategoryDropdownFilter(admin.SimpleListFilter):
    title = "Product Category"
    parameter_name = "product_category"

    # Use same template for consistent style
    template = "django_admin_listfilter_dropdown/dropdown_filter.html"  # same as RelatedOnlyDropdownFilter

    def lookups(self, request, model_admin):
        """Show only categories that appear in existing TransactionItems."""
        # collect all distinct category IDs from product or product.preferred
        used_category_ids = (
            TransactionItem.objects.filter(
                Q(product__category__isnull=False) | Q(product__preferred__category__isnull=False)
            )
            .values_list("product__category_id", flat=True)
            .union(
                TransactionItem.objects.filter(product__preferred__category__isnull=False)
                .values_list("product__preferred__category_id", flat=True)
            )
        )

        # return only those categories that actually appear
        categories = PurchaseCategory.objects.filter(id__in=used_category_ids).order_by("name")
        return [(c.id, c.name) for c in categories]

    def queryset(self, request, queryset):
        """Filter by related product category or preferred category."""
        value = self.value()
        if value:
            return queryset.filter(
                Q(product__category_id=value) | Q(product__preferred__category_id=value)
            )
        return queryset


# -----------------------------------
# INLINE ADMIN FOR TRANSACTION ITEMS
# -----------------------------------
class TransactionItemInline(admin.TabularInline):
    model = TransactionItem
    form = TransactionItemInlineForm
    extra = 0
    fields = ("product", "category_display", "quantity", "unit", "price")
    autocomplete_fields = ("product", )
    show_change_link = False
    classes = ('collapse',)

    def brand_display(self, obj):
        return obj.product.brand.name if obj.product and obj.product.brand else "-"
    brand_display.short_description = "Brand"

    def category_display(self, obj):
        if obj.product:
            preferred = obj.product.preferred
            if preferred and preferred.category:
                return preferred.category.name
            if obj.product.category:
                return obj.product.category.name
        return "-"
    category_display.short_description = "Category"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "unit":
            kwargs["queryset"] = Unit.objects.filter(preferred=None)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class TransactionSplitInlineForm(forms.ModelForm):
    """Custom form for TransactionSplit - split method is now in main Transaction form."""
    split_value = forms.DecimalField(
        required=False,
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'split-value-input', 'step': '0.01', 'placeholder': 'Enter value'}),
        help_text="Percentage (0-100) for percentage method, or shares count for shares method",
        label="Value"
    )

    class Meta:
        model = TransactionSplit
        fields = '__all__'
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Get split_value from existing data in notes JSONField
        if self.instance and self.instance.pk and self.instance.notes:
            notes = self.instance.notes if isinstance(self.instance.notes, dict) else {}
            split_value = notes.get('split_value')
            if split_value:
                self.fields['split_value'].initial = split_value
        
        # Make form-only fields not required
        self.fields['split_value'].required = False
    
    def save(self, commit=True):
        # Store split_value in notes JSONField (split_method is stored from main form)
        instance = super().save(commit=False)
        
        # Initialize notes as dict if None
        if instance.notes is None:
            instance.notes = {}
        elif not isinstance(instance.notes, dict):
            instance.notes = {}
        
        # Store split value metadata in notes
        split_value = self.cleaned_data.get('split_value')
        
        if split_value is not None:
            instance.notes['split_value'] = float(split_value)
        elif 'split_value' in instance.notes:
            del instance.notes['split_value']
        
        # Note: split_method is stored from the main Transaction form's save_model method
        
        if commit:
            instance.save()
        return instance


class TransactionSplitInline(admin.TabularInline):
    model = TransactionSplit
    form = TransactionSplitInlineForm
    formset = TransactionSplitFormSet
    extra = 0
    can_delete = False  # Enable deletion of split rows
    fields = ("id", "user", "split_value", "amount")  # Removed split_method - it's now in the main form
    autocomplete_fields = ("user",)
    verbose_name = "Split"
    verbose_name_plural = "Splits Among Friends"
    classes = ('collapse',)
    
    class Media:
        js = ('admin/js/split_calculator.js',) if False else ()  # Will be handled in template
    
    
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Override to show all users in the user field for splits, even with autocomplete."""
        
        from dal import autocomplete
        User = get_user_model()
        if db_field.name == "user":
            # Use .all() to bypass any default manager filtering that might restrict users
            # Show all active, non-deleted users for splits
            kwargs["queryset"] = User.objects.all().filter(is_active=True, is_deleted=False).order_by('email')
            
            # Explicitly set the autocomplete widget to use our custom UserAutocomplete view
            # This bypasses Django Admin's default autocomplete which uses UserAdmin.get_search_results
            kwargs["widget"] = autocomplete.ModelSelect2(
                url="user-autocomplete",
                attrs={
                    "data-placeholder": "Search user by email...",
                    "class": "user-autocomplete-no-buttons",
                },
            )
        
        # Get the formfield from parent
        formfield = super().formfield_for_foreignkey(db_field, request, **kwargs)
        
        # Ensure queryset is not restricted (needed for initial value display)
        if db_field.name == "user":
            formfield.queryset = User.objects.all().filter(is_active=True, is_deleted=False).order_by('email')
        
        return formfield


# -----------------------------------
# TRANSACTION ADMIN
# -----------------------------------
@admin.register(Transaction)
class TransactionAdmin(RestrictedAdmin):
    list_display = (
        "account",
        "transaction_type",
        "date",
        "store",
        "amount",
        "currency",
        "category",
        "totals_match"
    )
    search_fields = ("store__name", "description", "category__name", "account__name", 
                    "items__product__name", "items__product__preferred__name",  
                    "items__product__brand__preferred__name", "items__product__brand__name")

    list_filter = (
        ("date", DateRangeFilter),
        ("transaction_type", DropdownFilter),
        ("totals_match", admin.BooleanFieldListFilter),
        ("currency", RelatedOnlyDropdownFilter),
        ("account", RelatedOnlyDropdownFilter),
        ("category", RelatedOnlyDropdownFilter),
        ("store", RelatedOnlyDropdownFilter),
        ("created_by", RelatedOnlyDropdownFilter),
    )
    fieldsets = (
        ("📄 Basic Details", {
            "fields": ( "date", "transaction_type", "account", "to_account", "currency", "amount", "transaction_currency_amount", "exchange_rate", "fee_amount", "to_amount", "store", "category",),
        }),
        ("🏦 Extra", {
            "fields": ("description", "notes", "attachment"),
            "classes": ("collapse",),
        }),
        ("🔄 Transfers/Currency Exchange", {
            "fields": ("linked_transaction", "fee", "exchange_rate_record_display"),
            "classes": ("collapse",),
        }),
        ("📊 Computed / Status", {
            "fields": ("view_attachment", "total_from_items", "totals_match", "processed"),
            "classes": ("collapse",),
        }),
    )

    ordering = ("-date",)
    readonly_fields = ("linked_transaction", "fee", "exchange_rate_record_display", "processed", "view_attachment",
                        "created_at", "modified_at", "total_from_items", "totals_match")
    autocomplete_fields = ("category", "account", "currency", "store")
    inlines = [TransactionItemInline, TransactionSplitInline]
    change_list_template = "admin/invoice/invoice_changelist.html"
    actions = ["edit_selected"]

    def get_object(self, request, object_id, from_field=None):
        """Override to allow fetching transactions with splits even if not in queryset."""
        # First try the normal way (from queryset)
        try:
            obj = super().get_object(request, object_id, from_field)
            return obj
        except (Transaction.DoesNotExist, ValueError, AttributeError, PermissionDenied) as e:
            # If not found in queryset, try to get it directly if user has permission
            # This allows viewing transactions with splits even though they're not in the list
            try:
                # Try to get the object directly from the database
                obj = Transaction.objects.get(pk=object_id, is_deleted=False)
                # Check if user has permission to view this transaction
                if self.has_view_permission(request, obj):
                    return obj
                else:
                    # User doesn't have permission
                    raise PermissionDenied
            except Transaction.DoesNotExist:
                # Transaction doesn't exist at all
                pass
            # Re-raise the original exception if we can't find it or user doesn't have permission
            raise

    def has_view_permission(self, request, obj=None):
        """Allow viewing transactions where:
        1. The user created the transaction, OR
        2. The user has a split in the transaction
        """
        if request.user.is_superuser:
            return True
        
        if obj is None:
            # For list view, check queryset instead
            return True
        
        # User can view if they created the transaction
        if obj.created_by == request.user:
            return True
        
        # User can view if they have a split in the transaction
        if TransactionSplit.objects.filter(
            transaction=obj,
            user=request.user,
            is_deleted=False
        ).exists():
            return True
        
        return False

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        """Override to allow viewing transactions with splits even if not in queryset."""
        # For objects not in the queryset, we need to handle them specially
        if object_id:
            # First, try to get the object using our custom get_object
            # This will handle transactions with splits even if not in queryset
            try:
                obj = self.get_object(request, object_id)
                # Verify permission
                if not self.has_view_permission(request, obj):
                    raise PermissionDenied
                # If we got here, the object exists and user has permission
                # Now we need to temporarily modify the queryset to include this object
                # so Django admin's changeform_view can work with it
                original_get_queryset = self.get_queryset
                def patched_get_queryset(req):
                    qs = original_get_queryset(req)
                    # Add this object to the queryset if it's not already there
                    if not qs.filter(pk=obj.pk).exists():
                        # Use union to add this object
                        from django.db.models import Q
                        return qs.model.objects.filter(
                            Q(pk__in=qs.values_list('pk', flat=True)) | Q(pk=obj.pk)
                        )
                    return qs
                self.get_queryset = patched_get_queryset
                try:
                    return super().changeform_view(request, object_id, form_url, extra_context)
                finally:
                    # Restore original method
                    self.get_queryset = original_get_queryset
            except (Transaction.DoesNotExist, ValueError, AttributeError, PermissionDenied):
                # If we can't get the object or no permission, let Django handle the error
                pass
        
        # Normal case - call parent
        return super().changeform_view(request, object_id, form_url, extra_context)

    def edit_selected(self, request, queryset):
        """Bulk-edit selected transactions with DAL autocomplete support."""
        if "apply" in request.POST:
            form = BulkEditTransactionForm(request.POST, request=request)
            if form.is_valid():
                data = {k: v for k, v in form.cleaned_data.items() if v not in (None, "", [])}
                count = 0
                for obj in queryset:
                    for field, value in data.items():
                        setattr(obj, field, value)
                    obj.save()
                    count += 1

                messages.success(request, f"✅ Updated {count} transaction(s) successfully.")
                return redirect(request.get_full_path())
        else:
            form_initial = {}

            if queryset.exists():
                for field_name in ["transaction_type", "currency", "account", "category", "store"]:
                    values = list(queryset.values_list(field_name, flat=True))
                    unique_values = list(set(values))  # deduplicate manually
                    if len(unique_values) == 1:
                        shared_value = unique_values[0]
                        form_initial[field_name] = shared_value
                    else:
                        form_initial[field_name] = None
            form = BulkEditTransactionForm(request=request, initial=form_initial)

        context = dict(
            self.admin_site.each_context(request),
            title="Bulk Edit Transactions",
            queryset=queryset,
            form=form,
            opts=self.model._meta,
        )
        return render(request, "admin/transaction_bulk_edit.html", context)
    edit_selected.short_description = "Edit selected transactions"
    
    def save_model(self, request, obj, form, change):
        """Automatically set currency from selected account if not manually chosen."""
        super().save_model(request, obj, form, change)
        to_account = form.cleaned_data.get("to_account")
        fee_amount = form.cleaned_data.get("fee_amount")
        to_amount = form.cleaned_data.get("to_amount")
        manual_exchange_rate = form.cleaned_data.get("exchange_rate")
        
        # Handle transfer-specific logic (includes fee handling for transfers)
        if obj.transaction_type and "transfer" in obj.transaction_type and to_account:
            self.handle_transfer_transaction(request, obj, to_account, fee_amount, to_amount)
        else:
            # Handle cross-currency transactions (non-transfer)
            account_currency = getattr(obj.account, "currency", None) if obj.account else None
            transaction_currency = obj.currency
            
            # Check if this is a cross-currency transaction
            if account_currency and transaction_currency and account_currency != transaction_currency:
                # The amount field contains the transaction currency amount (user input)
                transaction_currency_amount = Decimal(str(obj.amount or 0))
                
                # Convert transaction currency amount to account currency amount
                if transaction_currency_amount > 0:
                    if manual_exchange_rate and manual_exchange_rate > 0:
                        # Use manual exchange rate: account_amount = transaction_amount * exchange_rate
                        # Exchange rate is: X account_currency = transaction_currency
                        # So: account_amount = transaction_amount * X
                        calculated_account_amount = transaction_currency_amount * Decimal(str(manual_exchange_rate))
                        obj.amount = calculated_account_amount.quantize(Decimal("0.01"))
                        obj.save(update_fields=["amount"])
                        logger.info(
                            f"[TransactionAdmin.save_model] Converted transaction amount {transaction_currency_amount} "
                            f"to account amount {obj.amount} using rate {manual_exchange_rate}"
                        )
                    else:
                        # Fetch market rate to calculate account amount
                        market_rate = fetch_market_rate(
                            base_code=getattr(account_currency, "code", str(account_currency)),
                            quote_code=getattr(transaction_currency, "code", str(transaction_currency)),
                            date_obj=obj.date or date.today(),
                        )
                        if market_rate:
                            calculated_account_amount = transaction_currency_amount * Decimal(str(market_rate))
                            obj.amount = calculated_account_amount.quantize(Decimal("0.01"))
                            obj.save(update_fields=["amount"])
                            logger.info(
                                f"[TransactionAdmin.save_model] Converted transaction amount {transaction_currency_amount} "
                                f"to account amount {obj.amount} using market rate {market_rate}"
                            )
                        else:
                            logger.warning(
                                f"[TransactionAdmin.save_model] Could not fetch market rate, "
                                f"keeping transaction amount as-is: {transaction_currency_amount}"
                            )
                
                # Calculate transaction currency amount from account amount for exchange rate record
                # This is the original input amount in transaction currency
                calculated_transaction_amount = transaction_currency_amount
                if obj.amount > 0 and transaction_currency_amount == 0:
                    # If amount was already converted, calculate back
                    if manual_exchange_rate and manual_exchange_rate > 0:
                        # transaction_amount = account_amount / exchange_rate
                        calculated_transaction_amount = Decimal(str(obj.amount)) / Decimal(str(manual_exchange_rate))
                    elif obj.exchange_rate_record:
                        calculated_transaction_amount = Decimal(str(obj.amount)) / Decimal(str(obj.exchange_rate_record.provider_rate))
                
                self.handle_cross_currency_transaction(
                    request, obj, account_currency, transaction_currency, 
                    float(calculated_transaction_amount) if calculated_transaction_amount > 0 else None,
                    manual_exchange_rate
                )
            
            # Handle fee for non-transfer transactions (fee is always in account currency)
            account_currency_for_fee = account_currency or transaction_currency
            if fee_amount and fee_amount > 0:
                create_fee_transaction(
                    parent_transaction=obj,
                    fee_amount=fee_amount,
                    user=request.user,
                    currency=account_currency_for_fee,  # Fee in account currency
                    store=obj.store,
                )
            elif obj.fee:
                # Remove fee transaction if fee_amount is cleared
                fee_tx = obj.fee
                obj.fee = None
                obj.save(update_fields=["fee"])
                fee_tx.delete()
                logger.info(f"[TransactionAdmin.save_model] Removed fee transaction {fee_tx.id} for {obj.id}")
        
        # Store split_method in all splits' notes
        split_method = form.cleaned_data.get("split_method", "equally")
        if split_method and obj.pk:
            for split in obj.splits.filter(is_deleted=False):
                if split.notes is None:
                    split.notes = {}
                elif not isinstance(split.notes, dict):
                    split.notes = {}
                split.notes['split_method'] = split_method
                split.save(update_fields=['notes'])

    def save_related(self, request, form, formsets, change):
        """Override to handle split cleanup and validation."""
        # Call parent to save all formsets first
        super().save_related(request, form, formsets, change)
        
        # After saving, check if we should clean up splits
        obj = form.instance
        if obj and obj.pk:
            # Get all non-deleted splits
            splits = TransactionSplit.objects.filter(
                transaction=obj,
                is_deleted=False
            )
            
            split_count = splits.count()
            
            # If there's only one split and it's the current user, delete it
            if split_count == 1:
                single_split = splits.first()
                if single_split and single_split.user == request.user:
                    logger.info(
                        f"[TransactionAdmin.save_related] Only current user split exists, "
                        f"deleting split {single_split.id} for transaction {obj.id}"
                    )
                    single_split.delete()
                elif single_split:
                    # Only one split but not current user - keep it
                    logger.debug(
                        f"[TransactionAdmin.save_related] Single split exists for user "
                        f"{single_split.user.email}, keeping it"
                    )
            elif split_count == 0:
                logger.debug(
                    f"[TransactionAdmin.save_related] No splits exist for transaction {obj.id}"
                )
            else:
                # Multiple splits exist - keep them all
                logger.debug(
                    f"[TransactionAdmin.save_related] {split_count} splits exist for transaction {obj.id}, keeping all"
                )

    def changelist_view(self, request, extra_context=None):
        func_name = f"{self.__class__.__name__}.changelist_view"
        # ⚠️ If this is a POST from an admin action (like edit_selected),
        # skip the totals logic completely — let Django admin handle the action.
        if request.method == "POST" and "action" in request.POST:
            return super().changelist_view(request, extra_context)

        # Otherwise proceed with your normal totals calculation
        response = super().changelist_view(request, extra_context=extra_context)
        if not isinstance(response, TemplateResponse):
            return response
        try:
            queryset = response.context_data["cl"].queryset

            # Define reusable decimal constants
            dec0 = Value(0, output_field=DecimalField(max_digits=20, decimal_places=2))
            dec_neg1 = Value(-1, output_field=DecimalField(max_digits=20, decimal_places=2))

            totals = (
                queryset.values("account__name", "currency__code")
                .annotate(
                    total=Coalesce(
                        Sum(
                            Case(
                                When(
                                    transaction_type__in=["credit", "transfer_credit"],
                                    then=ExpressionWrapper(F("amount"), output_field=DecimalField(max_digits=20, decimal_places=2)),
                                ),
                                When(
                                    transaction_type__in=["debit", "transfer_debit"],
                                    then=ExpressionWrapper(dec_neg1 * F("amount"), output_field=DecimalField(max_digits=20, decimal_places=2)),
                                ),
                                default=dec0,
                                output_field=DecimalField(max_digits=20, decimal_places=2),
                            ),
                            output_field=DecimalField(max_digits=20, decimal_places=2),
                        ),
                        dec0,
                    )
                )
                .order_by("account__name", "currency__code")
            )

            if totals.exists():
                html_lines = []
                for row in totals:
                    account = row["account__name"] or "—"
                    currency = row["currency__code"] or ""
                    total = round(row["total"], 2)
                    html_lines.append(f"<b>{account}</b>: {total:,} {currency}")

                total_html = "<br>".join(html_lines)
                response.context_data["custom_totals"] = format_html(total_html)
                logger.debug(f"[{func_name}] Calculated totals by account and currency: {totals}")

        except Exception as e:
            logger.exception(f"[{func_name}] Error generating totals for transaction list")
            raise e

        return response

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path("upload-bill/", self.admin_site.admin_view(self.upload_bill_view), name="transactions_upload_bill"),
            path("ajax/get-currency/", self.admin_site.admin_view(self.get_currency_from_account), name="transaction_get_currency"),
            path("ajax/get-currency-code/", self.admin_site.admin_view(self.get_currency_code), name="transaction_get_currency_code"),
            path("ajax/get-category/", self.admin_site.admin_view(self.get_category_from_store), name="transaction_get_category"),
        ]
        return custom_urls + urls

    def upload_bill_view(self, request):
        """Custom admin view to upload and process a bill or any financial document."""
        func_name = f"{self.__class__.__name__}.upload_bill_view"
        try:
            if request.method == "POST":
                uploaded_file = request.FILES.get("image")
                account_id = request.POST.get("account")
                browser_tz_str = request.POST.get("browser_timezone", "UTC")

                if not uploaded_file or not account_id:
                    logger.warning(f"[{func_name}] Missing file or account for {request.user.email}")
                    messages.error(request, "Please choose both account and file.")
                    return redirect("..")

                account = Account.objects.filter(id=account_id, created_by=request.user).first()
                if not account:
                    logger.warning(f"[{func_name}] Invalid account {account_id} by {request.user.email}")
                    messages.error(request, "Invalid account selected.")
                    return redirect("..")

                logger.info(f"[{func_name}] Processing file '{uploaded_file.name}' for account={account} by {request.user.email}")

                data = process_transaction_file(uploaded_file)
                doc_type = data.get("document_type", "unknown")
                transactions = data.get("transactions", [])

                if not transactions:
                    logger.warning(f"[{func_name}] No transactions found in uploaded {doc_type}")
                    messages.warning(request, f"⚠️ No transactions found in the uploaded {doc_type}.")
                    return redirect("..")

                logger.debug(f"[{func_name}] Detected {len(transactions)} transaction(s) in {doc_type}")
                created_or_updated = []

                for idx, tx_data in enumerate(transactions):
                    store_ref = tx_data.get("store")
                    date_val = tx_data.get("date") or timezone.now()
                    amount = tx_data.get("amount", 0)
                    category_ref = tx_data.get("category")
                    currency_ref = tx_data.get("currency")

                    try:
                        browser_tz = pytz.timezone(browser_tz_str)
                        if timezone.is_naive(date_val):
                            date_val = browser_tz.localize(date_val)
                        else:
                            date_val = date_val.astimezone(browser_tz)
                    except Exception as e:
                        logger.warning(f"[{func_name}] Could not convert timezone: {e}", exc_info=True)
                        date_val = timezone.localtime(date_val)

                    preferred_store = store_ref.preferred or store_ref
                    existing_tx = (
                        Transaction.objects.filter(
                            account=account,
                            created_by=request.user,
                            amount=amount,
                            date__range=(date_val - timedelta(days=2), date_val + timedelta(days=2)),
                        )
                        .filter(Q(store=preferred_store) | Q(store__preferred=preferred_store))
                        .first()
                    )

                    if existing_tx:
                        transaction = existing_tx
                        logger.info(f"[{func_name}] Updating existing transaction {transaction.id}")
                    else:
                        transaction = Transaction.objects.create(
                            id=uuid.uuid4(),
                            account=account,
                            transaction_type=tx_data.get("transaction_type", "debit"),
                            amount=0.0,
                            date=date_val,
                            processed=False,
                            created_by=request.user,
                        )
                        logger.info(f"[{func_name}] Created new transaction {transaction.id}")

                    transaction.store = store_ref
                    transaction.description = tx_data.get("description")
                    transaction.amount = amount
                    transaction.category = category_ref
                    transaction.currency = currency_ref
                    transaction.date = date_val
                    transaction.processed = True
                    transaction.save()
                    
                    # Create fee transaction if fee is present
                    fee_amount = tx_data.get("fee")
                    if fee_amount:
                        create_fee_transaction(
                            parent_transaction=transaction,
                            fee_amount=fee_amount,
                            user=request.user,
                            currency=currency_ref,
                            store=store_ref,
                        )

                    # Attach file only once
                    if idx == 0:
                        try:
                            # 1️⃣ Detect proper type using the shared utility
                            mime_type = uploaded_file.content_type or mimetypes.guess_type(uploaded_file.name)[0]
                            file_type = get_attachment_type(uploaded_file.name, mime_type)

                            # 2️⃣ Build a clean timestamped name
                            timestamp = date_val.strftime("%Y%m%d_%H%M%S")
                            extension = uploaded_file.name.split(".")[-1]
                            clean_store_name = preferred_store.name.replace(" ", "_")
                            custom_name = f"{file_type}_{clean_store_name}_{timestamp}.{extension}"

                            logger.debug(f"[{func_name}] Saving attachment type={file_type} mime={mime_type} name={custom_name}")

                            # 3️⃣ Create and save attachment
                            attachment = Attachment.objects.create(
                                created_by=transaction.created_by,
                                type=file_type,
                                description=f"{preferred_store.name} ({file_type})",
                                content_type=ContentType.objects.get_for_model(transaction),
                                object_id=transaction.id,
                            )

                            attachment.file.save(custom_name, uploaded_file, save=True)
                            transaction.attachment = attachment
                            transaction.save(update_fields=["attachment"])

                            logger.debug(f"[{func_name}] File attached as {custom_name}")
                        except Exception as e:
                            logger.warning(f"[{func_name}] Could not attach file: {e}", exc_info=True)


                    if existing_tx:
                        transaction.items.all().delete()
                        logger.debug(f"[{func_name}] Cleared old items for transaction {transaction.id}")

                    # The above code is defining a variable named `total_items_amount` in Python.
                    total_items_amount = 0
                    items = tx_data.get("items", None) 
                    if items:
                        for item_data in tx_data.get("items", []):
                            price = item_data.get("price", 0)
                            quantity = item_data.get("quantity", 1)
                            line_total = (price or 0) * (quantity or 1)
                            total_items_amount += line_total

                            TransactionItem.objects.create(
                                transaction=transaction,
                                product=item_data.get("item_ref"),
                                unit=item_data.get("unit_ref"),
                                quantity=quantity,
                                price=price,
                                date=date_val,
                            )
                    else:
                        total_items_amount = float(transaction.amount)

                    # ✅ Added total validation
                    try:
                        if round(total_items_amount, 2) != round(float(transaction.amount), 2):
                            diff = round(total_items_amount - float(transaction.amount), 2)
                            msg = f"⚠️ Transaction {transaction.id} items total ({total_items_amount}) " \
                                f"differs from transaction amount ({transaction.amount}) by {diff}."
                            messages.warning(request, msg)
                            logger.warning(f"[{func_name}] {msg}")
                        else:
                            logger.debug(f"[{func_name}] Transaction {transaction.id} item totals verified successfully.")
                    except Exception as e:
                        logger.warning(f"[{func_name}] Could not verify totals for transaction {transaction.id}: {e}", exc_info=True)

                    created_or_updated.append(transaction)

                msg_action = "Updated" if any(t for t in created_or_updated if t.id) else "Created"

                # ✅ Build summary list of store + date
                summary = []
                for t in created_or_updated:
                    store_name = getattr(getattr(t, "store", None), "name", "Unknown Store")
                    date_str = t.date.strftime("%Y-%m-%d") if getattr(t, "date", None) else "-"
                    summary.append(f"{store_name} ({date_str})")

                # ✅ Shorten message if too long
                if len(summary) > 5:
                    display_summary = ", ".join(summary[:5]) + f", and {len(summary) - 5} more..."
                else:
                    display_summary = ", ".join(summary)

                msg = f"{msg_action} {len(created_or_updated)} transaction(s) from '{doc_type}' document: {display_summary}"

                messages.success(request, msg)
                logger.info(f"[{func_name}] {msg}")

                return redirect("..")

        except Exception as e:
            logger.exception(f"[{func_name}] Error processing upload for {request.user.email}")
            messages.error(request, "Exception: " + str(e))
            return redirect("..")

        # GET request: render upload form
        context = dict(
            self.admin_site.each_context(request),
            title="Upload Bill or Transaction File",
            accounts=Account.objects.filter(created_by=request.user)
            .select_related("currency")
            .order_by("name"),
        )
        logger.debug(f"[{func_name}] Rendering upload form for {request.user.email}")
        return render(request, "admin/invoice/upload_bill.html", context)

    def view_attachment(self, obj):
        """
        Display a preview or a link for the attachment file.
        - Shows image preview if it's an image.
        - Shows clickable link for other file types.
        """
        if not getattr(obj, "attachment", None):
            return "-"

        file_field = obj.attachment.file if hasattr(obj.attachment, "file") else None
        if not file_field or not file_field.url:
            return "-"

        url = file_field.url
        mime_type, _ = mimetypes.guess_type(url)

        if mime_type and mime_type.startswith("image"):
            # ✅ Render image preview
            return format_html('<img src="{}" style="max-height:150px;border-radius:4px;"/>', url)
        else:
            # ✅ Render a simple “View File” link
            filename = os.path.basename(url)
            return format_html('<a href="{}" target="_blank">📎 View File ({})</a>', url, filename)
    view_attachment.short_description = "Invoice"

    def exchange_rate_record_display(self, obj):
        """Display exchange rate record with currency information."""
        if not obj or not obj.exchange_rate_record:
            return "—"
        
        exch = obj.exchange_rate_record
        base_currency = getattr(exch.base_currency, "code", "") if exch.base_currency else ""
        quote_currency = getattr(exch.quote_currency, "code", "") if exch.quote_currency else ""
        provider_rate = exch.provider_rate
        
        if base_currency and quote_currency and provider_rate:
            # Format: Exchange Rate: 1.1 USD = 1 EUR (Rate: 1.1)
            return format_html(
                '<strong>Exchange Rate:</strong> {} {} = 1 {} (Rate: {})',
                provider_rate,
                base_currency,
                quote_currency,
                provider_rate
            )
        elif base_currency and quote_currency:
            return format_html(
                '<strong>Exchange Rate:</strong> {} → {}',
                base_currency,
                quote_currency
            )
        else:
            return str(exch)
    exchange_rate_record_display.short_description = "Exchange Rate Record"

    def get_currency_from_account(self, request):
        """Return currency for a selected account."""
        account_id = request.GET.get("account_id")
        if not account_id:
            return JsonResponse({"error": "No account id provided"}, status=400)
        try:
            account = Account.objects.select_related("currency").get(id=account_id)
            return JsonResponse({
                "currency_id": account.currency.id if account.currency else None,
                "currency_name": account.currency.code if account.currency else None,
            })
        except Account.DoesNotExist:
            return JsonResponse({"error": "Invalid account id"}, status=404)

    def get_currency_code(self, request):
        """Return currency code for a selected currency."""
        from catalog.models import Currency
        currency_id = request.GET.get("currency_id")
        if not currency_id:
            return JsonResponse({"error": "No currency id provided"}, status=400)
        try:
            currency = Currency.objects.get(id=currency_id)
            return JsonResponse({
                "currency_code": currency.code if currency else None,
            })
        except Currency.DoesNotExist:
            return JsonResponse({"error": "Invalid currency id"}, status=404)

    def get_category_from_store(self, request):
        """Return category for a selected store."""
        store_id = request.GET.get("store_id")
        if not store_id:
            return JsonResponse({"error": "No store id provided"}, status=400)
        try:
            from catalog.models import Store  # import locally
            store = Store.objects.get(id=store_id)
            category = (
                store.preferred.categories.first()[0] if store.preferred and store.preferred.categories.first()
                else store.categories.first()
            )
            return JsonResponse({
                "category_id": category.id if category else None,
                "category_name": category.name if category else None,
            })
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    def get_form(self, request, obj=None, **kwargs):
        kwargs["form"] = TransactionForm
        form = super().get_form(request, obj, **kwargs)
        form.request = request
        return form

    @db_transaction.atomic
    def handle_transfer_transaction(self, request, obj, to_account, fee_amount, to_amount):
        """
        PRESERVES your original mapping of from/to/mirror accounts and amounts.
        Adds: safe Decimal conversion + skip fee/exrate for same-currency transfers.
        """
        func_name = f"{self.__class__.__name__}.handle_transfer_transaction"
        try:
            # -------------------------------
            # Your original mapping (unchanged)
            # -------------------------------
            if obj.transaction_type == "transfer_debit":
                mirror_type    = "transfer_credit"
                from_currency  = getattr(obj.account, "currency", None)
                to_currency    = getattr(to_account, "currency", None)
                to_amount      = _D(to_amount)                 # keep caller's to_amount
                from_amount    = _D(obj.amount or 0)          # from-side amount on this obj
                from_account   = obj.account
                mirror_account = to_account
                mirror_amount  = to_amount
            elif obj.transaction_type == "transfer_credit":
                mirror_type    = "transfer_debit"
                to_currency    = getattr(obj.account, "currency", None)
                from_currency  = getattr(to_account, "currency", None)
                from_amount    = _D(to_amount)                # your original: from_amount <- to_amount
                to_amount      = _D(obj.amount or 0)          # to-side amount on this obj
                from_account   = to_account
                to_account     = obj.account                  # preserve your reassignment
                mirror_account = from_account
                mirror_amount  = from_amount
            else:
                return  # not a transfer

            logger.info(
                f"[{func_name}] {obj.transaction_type}: "
                f"{from_account}({from_currency}) -> {mirror_account}({to_currency}); "
                f"from_amount={from_amount}, mirror_amount={mirror_amount}"
            )

            # -------------------------------
            # Same-currency rule
            # -------------------------------
            cross_currency = bool(from_currency and to_currency and from_currency != to_currency)

            # -------------------------------
            # Fee (for all transfers, not just cross-currency)
            # -------------------------------
            fee_tx = getattr(obj, "fee", None)
            fee_amount = _D(fee_amount)

            if fee_amount > 0:
                fee_percent = (float(fee_amount) / float(from_amount)) * 100 if from_amount else 0.0
                bank_fee_category = PurchaseCategory.objects.filter(name__iexact="Bank Fee").first()
                if not bank_fee_category:
                    bank_fee_category, _ = PurchaseCategory.objects.get_or_create(
                        name="Bank Fee",
                        defaults={"created_by": request.user}
                    )
                
                # Use Conversion Fees store for cross-currency, otherwise use transaction store
                if cross_currency:
                    conversion_store = Store.objects.filter(name__iexact="Conversion Fees").first()
                    if not conversion_store:
                        conversion_store, _ = Store.objects.get_or_create(
                            name="Conversion Fees",
                            defaults={"created_by": request.user, "category": bank_fee_category}
                        )
                    fee_store = conversion_store
                else:
                    fee_store = obj.store or Store.objects.filter(name__iexact="Bank Fee").first()

                if not fee_tx:
                    fee_tx = Transaction.objects.create(
                        created_by=request.user,
                        account=from_account,
                        transaction_type="debit",
                        amount=fee_amount,
                        date=obj.date,
                        currency=from_currency,
                        category=bank_fee_category,
                        store=fee_store,
                        description=f"Transfer fee for {obj.id}",
                    )
                    logger.info(f"[{func_name}] Created fee transaction {fee_tx.id} for {obj.id}")
                else:
                    fee_tx.account = from_account
                    fee_tx.amount = fee_amount
                    fee_tx.currency = from_currency
                    fee_tx.category = bank_fee_category
                    fee_tx.store = fee_store
                    fee_tx.date = obj.date
                    fee_tx.description = f"Transfer fee for {obj.id}"
                    fee_tx.save()
            else:
                fee_percent = 0.0
                # Remove existing fee transaction if fee_amount is cleared
                if fee_tx:
                    obj.fee = None
                    obj.save(update_fields=["fee"])
                    fee_tx.delete()
                    logger.info(f"[{func_name}] Removed fee transaction {fee_tx.id} for {obj.id}")
                fee_tx = None

            # -------------------------------
            # Exchange rate (only if cross-currency)
            # -------------------------------
            exchange_rate_record = getattr(obj, "exchange_rate_record", None)
            if cross_currency:
                try:
                    # your original provider rate direction: from_amount / to_amount_on_other_side
                    denom = mirror_amount if obj.transaction_type == "transfer_debit" else to_amount
                    denom = denom if denom else Decimal("1")
                    provider_rate = (from_amount / denom).quantize(Decimal("0.0001"))

                    market_rate = fetch_market_rate(
                        base_code=getattr(from_currency, "code", str(from_currency)),
                        quote_code=getattr(to_currency, "code", str(to_currency)),
                        date_obj=obj.date or date.today(),
                    )

                    if not exchange_rate_record:
                        exchange_rate_record = ExchangeRateRecord.objects.create(
                            base_currency=from_currency,
                            quote_currency=to_currency,
                            provider_rate=provider_rate,
                            market_rate=market_rate,
                            fee_percent=fee_percent,
                            created_by=request.user,
                            date=obj.date,
                        )

                    provider = None
                    if getattr(obj, "store", None):
                        provider, _ = Institution.objects.get_or_create(
                            short_name__iexact=obj.store.name,
                            defaults={"short_name": obj.store.name.strip(), "created_by": request.user},
                        )

                    exchange_rate_record.base_currency   = from_currency
                    exchange_rate_record.quote_currency  = to_currency
                    exchange_rate_record.provider_rate   = provider_rate
                    exchange_rate_record.market_rate     = market_rate
                    exchange_rate_record.fee_percent     = fee_percent
                    exchange_rate_record.provider        = provider
                    exchange_rate_record.date            = obj.date
                    exchange_rate_record.save()
                except (InvalidOperation, ZeroDivisionError) as e:
                    logger.warning(f"[{func_name}] Invalid rate computation: {e}")
                except Exception as e:
                    logger.warning(f"[{func_name}] Could not create/update ExchangeRateRecord: {e}", exc_info=True)
            else:
                exchange_rate_record = None  # enforce rule for same-currency

            if not cross_currency:
                mirror_amount = _D(obj.amount or 0) 

            # -------------------------------
            # Mirror creation (preserve your mapping)
            # -------------------------------
            mirror = obj.linked_transaction
            if not mirror:
                mirror = (
                    Transaction.objects.filter(linked_transaction=obj).first()
                    or Transaction.objects.create(
                        created_by=request.user,
                        account=mirror_account,
                        transaction_type=mirror_type,
                        linked_transaction=obj,
                        amount=_D(mirror_amount),            # ensure NOT NULL
                        currency=to_currency,                # mirror currency is the "to" side
                    )
                )
                obj.linked_transaction = mirror

            # Update mirror in place
            mirror.transaction_type      = mirror_type
            mirror.account               = mirror_account
            mirror.date                  = obj.date
            mirror.category              = obj.category
            mirror.currency              = to_currency
            mirror.exchange_rate_record  = exchange_rate_record
            mirror.fee                   = fee_tx
            mirror.store                 = obj.store
            mirror.amount                = _D(mirror_amount)
            mirror.linked_transaction    = obj
            mirror.processed             = True
            mirror.save()

            # -------------------------------
            # Update original
            # -------------------------------
            obj.linked_transaction      = mirror
            obj.fee                     = fee_tx
            obj.exchange_rate_record    = exchange_rate_record
            obj.save(update_fields=["exchange_rate_record", "fee", "linked_transaction"])

            self.message_user(request, "✅ Mirror and related records created/updated successfully.")

        except Exception as e:
            logger.exception(f"[{func_name}] Error handling transfer for {obj.id}: {e}")
            self.message_user(request, f"⚠️ Error creating mirror/fee/exchange records: {e}", level="error")

    @db_transaction.atomic
    def handle_cross_currency_transaction(self, request, obj, account_currency, transaction_currency, 
                                        transaction_currency_amount=None, manual_exchange_rate=None):
        """
        Handle cross-currency transactions (non-transfer).
        Creates exchange rate record and ensures proper currency handling.
        
        Args:
            request: HTTP request
            obj: Transaction instance
            account_currency: Currency of the account
            transaction_currency: Currency of the transaction
            transaction_currency_amount: Amount in transaction currency (if different from obj.amount)
            manual_exchange_rate: Manual exchange rate (X account_currency = transaction_currency)
        """
        func_name = "handle_cross_currency_transaction"
        
        try:
            from_amount = Decimal(str(obj.amount or 0))
            transaction_amount = Decimal(str(transaction_currency_amount or 0))
            
            # Calculate exchange rate
            # Exchange rate direction: X account_currency = transaction_currency
            # So if account has 110 USD and transaction is 100 EUR, rate = 110/100 = 1.1 (1.1 USD = 1 EUR)
            if manual_exchange_rate and manual_exchange_rate > 0:
                provider_rate = Decimal(str(manual_exchange_rate))
            elif transaction_currency_amount and transaction_currency_amount > 0 and from_amount > 0:
                # Calculate from amounts: provider_rate = account_amount / transaction_currency_amount
                # This gives: provider_rate account_currency = transaction_currency
                provider_rate = (from_amount / transaction_amount).quantize(Decimal("0.0001"))
            else:
                # If no transaction currency amount provided, we can't calculate the rate
                # Will use market rate as fallback
                provider_rate = None
            
            # Fetch market rate
            market_rate = fetch_market_rate(
                base_code=getattr(account_currency, "code", str(account_currency)),
                quote_code=getattr(transaction_currency, "code", str(transaction_currency)),
                date_obj=obj.date or date.today(),
            )
            
            # Use market rate as provider_rate if not calculated
            if provider_rate is None:
                provider_rate = market_rate if market_rate else Decimal("1")
                logger.info(f"[{func_name}] Using market rate as provider rate: {provider_rate}")
            
            # Calculate fee percent (if fee exists)
            fee_percent = Decimal("0")
            if obj.fee and obj.fee.amount:
                fee_amount = Decimal(str(obj.fee.amount))
                fee_percent = (float(fee_amount) / float(from_amount)) * 100 if from_amount > 0 else Decimal("0")
            
            # Get or create exchange rate record
            exchange_rate_record = getattr(obj, "exchange_rate_record", None)
            
            # Determine provider (from store or account institution)
            provider = None
            if obj.store:
                provider, _ = Institution.objects.get_or_create(
                    short_name__iexact=obj.store.name,
                    defaults={"short_name": obj.store.name.strip(), "created_by": request.user},
                )
            elif obj.account and obj.account.institution:
                provider = obj.account.institution
            
            if not exchange_rate_record:
                exchange_rate_record = ExchangeRateRecord.objects.create(
                    base_currency=account_currency,
                    quote_currency=transaction_currency,
                    provider_rate=provider_rate,
                    market_rate=market_rate,
                    fee_percent=fee_percent,
                    provider=provider,
                    created_by=request.user,
                    date=obj.date,
                )
                logger.info(
                    f"[{func_name}] Created exchange rate record {exchange_rate_record.id} "
                    f"for transaction {obj.id}: 1 {account_currency.code} = {provider_rate} {transaction_currency.code}"
                )
            else:
                # Update existing record
                exchange_rate_record.base_currency = account_currency
                exchange_rate_record.quote_currency = transaction_currency
                exchange_rate_record.provider_rate = provider_rate
                exchange_rate_record.market_rate = market_rate
                exchange_rate_record.fee_percent = fee_percent
                exchange_rate_record.provider = provider
                exchange_rate_record.date = obj.date
                exchange_rate_record.save()
                logger.info(
                    f"[{func_name}] Updated exchange rate record {exchange_rate_record.id} "
                    f"for transaction {obj.id}: 1 {account_currency.code} = {provider_rate} {transaction_currency.code}"
                )
            
            # Link exchange rate record to transaction
            obj.exchange_rate_record = exchange_rate_record
            
            # Change transaction currency to account currency after exchange rate record is created
            # The amount is now stored in account currency, so transaction currency should match
            if obj.currency != account_currency:
                old_currency = obj.currency
                obj.currency = account_currency
                logger.info(
                    f"[{func_name}] Changed transaction currency from {old_currency.code} "
                    f"to {account_currency.code} for transaction {obj.id}"
                )
            
            obj.save(update_fields=["exchange_rate_record", "currency"])
            
        except Exception as e:
            logger.exception(f"[{func_name}] Error handling cross-currency transaction: {e}")
            # Don't fail the transaction save, just log the error


# -----------------------------------
# OWES ADMIN (Custom View)
# -----------------------------------
@admin.register(OwesDummyModel)
class OwesAdmin(admin.ModelAdmin):
    """Admin for the Owes summary view."""
    
    def has_add_permission(self, request):
        """Disable add permission - this is a view-only admin."""
        return False
    
    def has_change_permission(self, request, obj=None):
        """Disable change permission - this is a view-only admin."""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Disable delete permission - this is a view-only admin."""
        return False
    
    def has_view_permission(self, request, obj=None):
        """Allow all authenticated users to view the owes summary."""
        return request.user.is_authenticated
    
    def changelist_view(self, request, extra_context=None):
        """Show the owes view directly."""
        return _render_owes_view(request, self.admin_site, self.model._meta)


# -----------------------------------
# TRANSACTION ITEM ADMIN
# -----------------------------------
@admin.register(TransactionItem)
class TransactionItemAdmin(RestrictedAdmin):
    list_display = ("transaction", "product", "product_category", "quantity", "unit", "price", "date")
    readonly_fields = ("created_at", "modified_at")
    search_fields = ("product__name", "product__category__name",
                        "product__preferred__name", "product__brand__preferred__name", "product__brand__name")
    list_filter = (
        ("unit", RelatedOnlyDropdownFilter), 
        ProductCategoryDropdownFilter,
        ("created_by", RelatedOnlyDropdownFilter),
    )
    ordering = ("-date",)
    autocomplete_fields = ("transaction", "product", "unit")
    actions = ["edit_selected"]

    def product_category(self, obj):
        if obj.product:
            preferred = obj.product.preferred
            if preferred and preferred.category:
                return preferred.category.name
            if obj.product.category:
                return obj.product.category.name
        return "-"
    product_category.short_description = "Category"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "unit":
            kwargs["queryset"] = Unit.objects.filter(preferred=None)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
    
    def edit_selected(self, request, queryset):
        """Bulk edit selected TransactionItems."""
        if "apply" in request.POST:
            selected_ids = request.POST.getlist("_selected_action")
            queryset = self.model.objects.filter(pk__in=selected_ids)
            form = BulkEditTransactionItemForm(request.POST, request=request)
            if form.is_valid():
                data = {k: v for k, v in form.cleaned_data.items() if v not in (None, "", [])}
                count = 0
                for obj in queryset:
                    for field, value in data.items():
                        setattr(obj, field, value)
                    obj.save()
                    count += 1
                self.message_user(request, f"✅ Updated {count} transaction item(s) successfully.")
                return redirect(request.get_full_path())
        else:
            # Prefill if all selected have the same value
            form_initial = {}
            if queryset.exists():
                for field_name in ["product", "unit"]:
                    values = list(queryset.values_list(field_name, flat=True))
                    unique_values = list(set(values))
                    if len(unique_values) == 1:
                        form_initial[field_name] = unique_values[0]
            form = BulkEditTransactionItemForm(request=request, initial=form_initial)

        context = dict(
            self.admin_site.each_context(request),
            title="Bulk Edit Transaction Items",
            queryset=queryset,
            form=form,
            opts=self.model._meta,
        )
        return render(request, "admin/transaction_item_bulk_edit.html", context)
    edit_selected.short_description = "Edit selected transaction items"
