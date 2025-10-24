import uuid
import sys
import pytz
from datetime import timedelta

from django.contrib import admin, messages
from django.shortcuts import render, redirect
from django.db.models import Sum, Case, When, F, Q, DecimalField
from django.urls import path
from django.utils import timezone
from django.utils.html import format_html
from rangefilter.filters import DateRangeFilter

from account.models import Account
from transaction.admin_forms import TransactionItemInlineForm
from transaction.models import Transaction, TransactionItem
from transaction.invoice_handling import process_transaction_file
from django.contrib.admin import RelatedOnlyFieldListFilter
from user.admin import RestrictedAdmin

from common.logging_config import logger


# -----------------------------------
# INLINE ADMIN FOR TRANSACTION ITEMS
# -----------------------------------
class TransactionItemInline(admin.TabularInline):
    model = TransactionItem
    form = TransactionItemInlineForm
    extra = 0
    fields = ("product", "brand_display", "category_display", "quantity", "unit", "price")
    can_delete = False
    show_change_link = False

    class Media:
        css = {
            "all": ("admin/css/transaction_item_inline.css",)
        }

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
        "fee",
    )
    search_fields = ("store__name", "description", "category__name")
    list_filter = (
        ("date", DateRangeFilter),
        "transaction_type",
        ("currency", RelatedOnlyFieldListFilter),
        ("account", RelatedOnlyFieldListFilter),
        ("category", RelatedOnlyFieldListFilter),
        ("store", RelatedOnlyFieldListFilter),
    )
    ordering = ("-date",)
    readonly_fields = ("processed", "view_attachment", "created_at", "modified_at")
    inlines = [TransactionItemInline]
    change_list_template = "admin/invoice/invoice_changelist.html"

    def changelist_view(self, request, extra_context=None):
        func_name = f"{self.__class__.__name__}.changelist_view"
        response = super().changelist_view(request, extra_context=extra_context)
        try:
            queryset = response.context_data["cl"].queryset
            totals = (
                queryset.values("currency__code")
                .annotate(
                    total=Sum(
                        Case(
                            When(transaction_type__in=["credit", "transfer_credit"], then=F("amount")),
                            When(transaction_type__in=["debit", "transfer_debit"], then=-F("amount")),
                            default=0,
                            output_field=DecimalField(max_digits=20, decimal_places=2),
                        )
                    )
                )
                .order_by("currency__code")
            )

            if totals:
                total_html = "<br>".join(
                    f"<b>{row['currency__code']}</b>: {round(row['total'], 2):,}" for row in totals
                )
                response.context_data["custom_totals"] = format_html(total_html)
                logger.debug(f"[{func_name}] Calculated totals by currency: {totals}")
        except Exception as e:
            logger.exception(f"[{func_name}] Error generating totals for transaction list")
            raise e
        return response

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path("upload-bill/", self.admin_site.admin_view(self.upload_bill_view), name="transactions_upload_bill"),
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
                        logger.warning(f"[{func_name}] Could not convert timezone: {e}")
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

                    # Attach file only once
                    if idx == 0:
                        try:
                            timestamp = date_val.strftime("%Y%m%d_%H%M%S")
                            extension = uploaded_file.name.split(".")[-1]
                            custom_name = f"{doc_type}_{preferred_store.name}_{timestamp}.{extension}"
                            transaction.attachment.save(custom_name, uploaded_file, save=True)
                            logger.debug(f"[{func_name}] File attached as {custom_name}")
                        except Exception as e:
                            logger.warning(f"[{func_name}] Could not attach file: {e}")

                    if existing_tx:
                        transaction.items.all().delete()
                        logger.debug(f"[{func_name}] Cleared old items for transaction {transaction.id}")

                    for item_data in tx_data.get("items", []):
                        TransactionItem.objects.create(
                            transaction=transaction,
                            product=item_data.get("item_ref"),
                            unit=item_data.get("unit_ref"),
                            quantity=item_data.get("quantity", 1),
                            price=item_data.get("price", 0),
                            date=date_val,
                        )
                    created_or_updated.append(transaction)

                msg_action = "Updated" if any(t for t in created_or_updated if t.id) else "Created"
                messages.success(request, f"{msg_action} {len(created_or_updated)} transaction(s) from '{doc_type}' document.")
                logger.info(f"[{func_name}] {msg_action} {len(created_or_updated)} transactions for user={request.user.email}")

                return redirect("..")
        except Exception as e:
            logger.exception(f"[{func_name}] Error processing upload for {request.user.email}")
            messages.error(request, "Invalid account selected.")
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
        if obj.attachment:
            return format_html('<img src="{}" style="max-height:150px;"/>', obj.attachment.url)
        return "-"
    view_attachment.short_description = "Invoice"


# -----------------------------------
# TRANSACTION ITEM ADMIN
# -----------------------------------
@admin.register(TransactionItem)
class TransactionItemAdmin(RestrictedAdmin):
    list_display = ("transaction", "product", "product_category", "quantity", "unit", "price", "date")
    readonly_fields = ("created_at", "modified_at")
    search_fields = ("product__name",)
    list_filter = ("unit",)
    ordering = ("-date",)
    autocomplete_fields = ("transaction", "product", "unit")

    def product_category(self, obj):
        if obj.product:
            preferred = obj.product.preferred
            if preferred and preferred.category:
                return preferred.category.name
            if obj.product.category:
                return obj.product.category.name
        return "-"
    product_category.short_description = "Category"
