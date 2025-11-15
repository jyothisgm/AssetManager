from decimal import Decimal, InvalidOperation
import mimetypes
import os
import uuid
import pytz
from datetime import timedelta
from datetime import date

from django.contrib import admin, messages
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
from transaction.admin_forms import BulkEditTransactionForm, TransactionForm, TransactionItemInlineForm
from transaction.models import Transaction, TransactionItem
from transaction.invoice_handling import process_transaction_file
from user.admin import RestrictedAdmin
from django_admin_listfilter_dropdown.filters import RelatedOnlyDropdownFilter, DropdownFilter
from django.db.models.functions import Coalesce
from django.db import transaction as db_transaction

from common.logging_config import logger
from user.models import Attachment, get_attachment_type

from transaction.admin_forms import BulkEditTransactionItemForm  # safe import here


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
            "fields": ( "date", "transaction_type", "account", "to_account", "amount", "fee_amount", "to_amount", "store", "category",),
        }),
        ("🏦 Extra", {
            "fields": ("currency", "description", "notes", "attachment"),
            "classes": ("collapse",),
        }),
        ("🔄 Transfers/Currency Exchange", {
            "fields": ("linked_transaction", "fee", "exchange_rate_record"),
            "classes": ("collapse",),
        }),
        ("📊 Computed / Status", {
            "fields": ("view_attachment", "total_from_items", "totals_match", "processed"),
            "classes": ("collapse",),
        }),
    )

    ordering = ("-date",)
    readonly_fields = ("linked_transaction", "fee", "exchange_rate_record", "processed", "view_attachment",
                        "created_at", "modified_at", "total_from_items", "totals_match")
    autocomplete_fields = ("category", "account", "currency", "store", "attachment")
    inlines = [TransactionItemInline]
    change_list_template = "admin/invoice/invoice_changelist.html"
    actions = ["edit_selected"]

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
        
        # Handle transfer-specific logic (includes fee handling for transfers)
        if obj.transaction_type and "transfer" in obj.transaction_type and to_account:
            self.handle_transfer_transaction(request, obj, to_account, fee_amount, to_amount)
        else:
            # Handle fee for non-transfer transactions
            if fee_amount and fee_amount > 0:
                create_fee_transaction(
                    parent_transaction=obj,
                    fee_amount=fee_amount,
                    user=request.user,
                    currency=obj.currency,
                    store=obj.store,
                )
            elif obj.fee:
                # Remove fee transaction if fee_amount is cleared
                fee_tx = obj.fee
                obj.fee = None
                obj.save(update_fields=["fee"])
                fee_tx.delete()
                logger.info(f"[TransactionAdmin.save_model] Removed fee transaction {fee_tx.id} for {obj.id}")

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
