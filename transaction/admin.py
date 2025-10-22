import uuid
import sys
import pytz
from datetime import timedelta

from django.contrib import admin, messages
from django.shortcuts import render, redirect
from django.urls import path
from django.utils import timezone
from django.utils.html import format_html

from account.models import Account
from transaction.admin_forms import TransactionItemInlineForm
from transaction.models import Transaction, TransactionItem
from transaction.invoice_handling import process_bill_image
from django.contrib.admin import RelatedOnlyFieldListFilter


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
        if obj.product and obj.product.brand:
            return obj.product.brand.name
        return "-"
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
class TransactionAdmin(admin.ModelAdmin):
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
    search_fields = (
        "store__name",
        "description",
        "category__name",
    )
    readonly_fields = ("processed", "view_attachment", "created_at", "modified_at")
    list_filter = (
        "transaction_type",
        ("currency", RelatedOnlyFieldListFilter),
        ("account", RelatedOnlyFieldListFilter),
        ("category", RelatedOnlyFieldListFilter),
        ("store", RelatedOnlyFieldListFilter),
        
    )
    ordering = ("-date",)
    inlines = [TransactionItemInline]
    change_list_template = "admin/invoice/invoice_changelist.html"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path("upload-bill/", self.admin_site.admin_view(self.upload_bill_view), name="transactions_upload_bill"),
        ]
        return custom_urls + urls

    def upload_bill_view(self, request):
        """Custom admin view to upload and process a bill image."""

        if request.method == "POST":
            uploaded_file = request.FILES.get("image")
            account_id = request.POST.get("account")
            browser_tz_str = request.POST.get("browser_timezone", "UTC")

            if not uploaded_file or not account_id:
                messages.error(request, "Please choose both account and file.")
                return redirect("..")

            account = Account.objects.filter(id=account_id).first()
            if not account:
                messages.error(request, "Invalid account selected.")
                return redirect("..")

            try:
                data = process_bill_image(uploaded_file)
                store_ref = data.get("store")
                date_val = data.get("date") or timezone.now()
                amount = data.get("amount", 0)
                category_ref = data.get("category")
                currency_ref = data.get("currency")

                # 🕒 Adjust to user's browser timezone
                try:
                    browser_tz = pytz.timezone(browser_tz_str)
                    if timezone.is_naive(date_val):
                        date_val = browser_tz.localize(date_val)
                    else:
                        date_val = date_val.astimezone(browser_tz)
                except Exception as e:
                    print(f"⚠️ Could not convert timezone: {e}")
                    date_val = timezone.localtime(date_val)


                # --- Normalize store for matching ---
                preferred_store = store_ref.preferred or store_ref

                # 2️⃣ Try to find an existing transaction (same store/date/amount)
                existing_tx = (
                    Transaction.objects.filter(
                        account=account,
                        store__preferred=preferred_store,
                        amount=amount,
                        date__range=(date_val - timedelta(days=1), date_val + timedelta(days=1)),
                    )
                )

                if existing_tx:
                    transaction = existing_tx
                    print(f"♻️ Updating existing transaction {transaction.id}")
                else:
                    transaction = Transaction.objects.create(
                        id=uuid.uuid4(),
                        account=account,
                        transaction_type="debit",
                        amount=0.0,
                        date=date_val,
                        processed=False,
                    )
                    print(f"🆕 Created new placeholder transaction {transaction.id}")

                # 3️⃣ Update core fields
                transaction.store = store_ref
                transaction.description = data.get("description")
                transaction.amount = amount
                transaction.category = category_ref
                transaction.currency = currency_ref
                transaction.date = date_val
                transaction.save()

                # 4️⃣ Save or replace attachment
                try:
                    timestamp = date_val.strftime("%Y%m%d_%H%M%S")
                    extension = uploaded_file.name.split(".")[-1]
                    custom_name = f"receipt_{preferred_store.name}_{timestamp}.{extension}"
                    transaction.attachment.save(custom_name, uploaded_file, save=True)
                    print("🧾 Attachment saved.")
                except Exception as e:
                    print(f"⚠️ Could not rename image: {e}")

                # 5️⃣ Clear old items if updating
                if existing_tx:
                    transaction.items.all().delete()
                    print("🗑️ Old items cleared.")

                # 6️⃣ Create new transaction items
                for item_data in data.get("items", []):
                    TransactionItem.objects.create(
                        transaction=transaction,
                        product=item_data.get("item_ref"),
                        unit=item_data.get("unit_ref"),
                        quantity=item_data.get("quantity", 1),
                        price=item_data.get("price", 0),
                    )

                transaction.processed = True
                transaction.save()
                messages.success(
                    request,
                    f"{'♻️ Updated' if existing_tx else '✅ Created'} transaction for '{preferred_store.name}' ({date_val.date()}, {amount})",
                )

            except Exception as e:
                tb = sys.exc_info()[2]
                line_number = tb.tb_lineno
                messages.error(request, f"⚠️ Error processing bill: {e} (line {line_number})")
                return redirect("..")

            return redirect("..")

        # GET request: show upload form
        context = dict(
            self.admin_site.each_context(request),
            title="Upload Bill Image",
            accounts=Account.objects.select_related("currency").order_by("name"),
        )
        return render(request, "admin/invoice/upload_bill.html", context)
    
    #----------------------------
    # INLINE IMAGE PREVIEW
    # ----------------------------
    def view_attachment(self, obj):
        if obj.attachment:
            return format_html('<img src="{}" style="max-height:150px;"/>', obj.attachment.url)
        return "-"
    view_attachment.short_description = "Invoice"


# -----------------------------------
# TRANSACTION ITEM ADMIN
# -----------------------------------
@admin.register(TransactionItem)
class TransactionItemAdmin(admin.ModelAdmin):
    list_display = (
        "transaction",
        "product",
        "product_category",
        "quantity",
        "unit",
        "price",
        "created_at",
    )
    readonly_fields = ("created_at", "modified_at")
    search_fields = ("product__name",)
    list_filter = ("unit",)
    ordering = ("-created_at",)
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
