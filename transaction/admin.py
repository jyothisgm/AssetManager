import mimetypes
import os
import uuid
import pytz
from datetime import timedelta

from django.contrib import admin, messages
from django.shortcuts import render, redirect
from django.db.models import Sum, Case, When, F, Q, DecimalField, Value, ExpressionWrapper
from django.urls import path
from django.utils import timezone
from django.utils.html import format_html
from rangefilter.filters import DateRangeFilter
from django.contrib.contenttypes.models import ContentType

from account.models import Account
from catalog.models import PurchaseCategory
from common.models import Unit
from transaction.admin_forms import TransactionItemInlineForm
from transaction.models import Transaction, TransactionItem
from transaction.invoice_handling import process_transaction_file
from user.admin import RestrictedAdmin
from django_admin_listfilter_dropdown.filters import RelatedOnlyDropdownFilter, DropdownFilter
from django.db.models.functions import Coalesce

from common.logging_config import logger
from user.models import Attachment, get_attachment_type


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
            "fields": ( "date", "account", "transaction_type", "amount", "category", "store"),
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
    readonly_fields = ("processed", "view_attachment", "created_at", "modified_at", "total_from_items", "totals_match")
    autocomplete_fields = ("category", "account", "currency", "store", "attachment")
    inlines = [TransactionItemInline]
    change_list_template = "admin/invoice/invoice_changelist.html"
    
    def save_model(self, request, obj, form, change):
        """Automatically set currency from selected account if not manually chosen."""
        if obj.account and not obj.currency:
            obj.currency = obj.account.currency
        super().save_model(request, obj, form, change)

    def changelist_view(self, request, extra_context=None):
        func_name = f"{self.__class__.__name__}.changelist_view"
        response = super().changelist_view(request, extra_context=extra_context)
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
