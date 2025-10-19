from django.contrib import admin
from django.utils.html import format_html
import os
from django.shortcuts import render, redirect
from django.urls import path
from django.contrib import messages
from datetime import datetime
from django.utils import timezone
import uuid
from django.core.files.storage import default_storage
from .models import (
    Bill,
    BillItem,
    Store,
    ItemName,
    Unit,
    CategoryGroup, 
    PurchaseCategory,
    Brand
)
from .utils import process_bill_image, get_or_create_item_name, get_or_create_unit


@admin.register(CategoryGroup)
class CategoryGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "category_count", "created_at", "modified_at")
    search_fields = ("name",)

    def category_count(self, obj):
        return obj.categories.count()
    category_count.short_description = "No. of Categories"


@admin.register(PurchaseCategory)
class PurchaseCategoryAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "preferred_display",
        "group_list",
        "variant_count",
        "created_at",
        "modified_at",
    )
    filter_horizontal = ("groups",)  # ✅ allows multi-select UI
    search_fields = ("name",)
    list_filter = ("groups",)

    def preferred_display(self, obj):
        return obj.preferred.name if obj.preferred else "-"
    preferred_display.short_description = "Preferred Category"

    def group_list(self, obj):
        return ", ".join([g.name for g in obj.groups.all()])
    group_list.short_description = "Groups"

    def variant_count(self, obj):
        return obj.variants.count()

@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ("name", "preferred", "created_at")
    search_fields = ("name",)
    ordering = ("name",)


# ------------------------------
# INLINE ITEMS
# ------------------------------
class BillItemInline(admin.TabularInline):
    model = BillItem
    extra = 0
    fields = ("item_name", "item_name_raw", "quantity", "unit", "price")

    can_delete = False
    show_change_link = False


# ------------------------------
# STORE ADMIN
# ------------------------------
@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ("name", "preferred_name", "category_name", "variant_count", "created_at", "modified_at")
    search_fields = ("name",)

    def preferred_name(self, obj):
        return obj.preferred.name if obj.preferred else "-"
    
    def category_name(self, obj):
        return obj.category.name if obj.category else "-"
    category_name.short_description = "Category"

    def variant_count(self, obj):
        return obj.variants.count()


# ------------------------------
# ITEM NAME ADMIN
# ------------------------------
@admin.register(ItemName)
class ItemNameAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "preferred_display",
        "brand_display",
        "preferred_unit_display",
        "variant_count",
        "created_at",
        "modified_at",
    )
    search_fields = ("name", "brand__name")
    list_filter = ("preferred_unit", "brand")
    autocomplete_fields = ("preferred", "brand", "preferred_unit")
    ordering = ("name",)

    # --- Display helpers ---
    def preferred_display(self, obj):
        """Show canonical item name (preferred variant)"""
        if obj.preferred:
            return obj.preferred.name
        return "–"
    preferred_display.short_description = "Canonical Item"

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
# BILL ADMIN
# ------------------------------
'''
@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = (
        "store",
        "store_name_raw",
        "bill_date",
        "purchase_category",
        "total_amount",
        "processed",
        "created_at",
    )
    readonly_fields = ("processed", "created_at", "modified_at", "view_image")
    ordering = ("-created_at",)
    inlines = [BillItemInline]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        # Only process if not done before and has an image
        if not obj.processed and obj.image:
            data = process_bill_image(obj.image.path)

            # Save normalized store info
            obj.store = data.get("store")
            obj.store_name_raw = data.get("store_name_raw", "")
            obj.store_name_normalized = data.get("store_name_normalized", "")
            obj.bill_date = data.get("bill_date")
            category_name = data.get("category")
            category_ref = None
            if category_name:
                category_ref = PurchaseCategory.objects.filter(name__iexact=category_name).first()

            obj.purchase_category = category_ref
            obj.total_amount = data.get("total_amount", 0)
            obj.save()
            
            # --- Rename image file safely ---
            try:
                old_path = obj.image.path
                store_name = obj.store_name_normalized or obj.store_name_raw or "store"
                store_name = store_name.replace(" ", "_").replace("/", "_")

                timestamp = (
                    obj.bill_date.strftime("%Y%m%d_%H%M%S")
                    if obj.bill_date
                    else datetime.now().strftime("%Y%m%d_%H%M%S")
                )

                ext = os.path.splitext(old_path)[1] or ".jpg"
                new_filename = f"{store_name}_{timestamp}{ext}"

                # Use the same upload directory
                upload_dir = os.path.dirname(old_path)
                new_path = os.path.join(upload_dir, new_filename)

                # Rename file on disk
                os.rename(old_path, new_path)

                # Update the ImageField reference
                relative_path = os.path.relpath(new_path, default_storage.location)
                obj.image.name = relative_path
                obj.save()
                print(f"✅ Renamed bill image to {new_filename}")
            except Exception as e:
                print(f"⚠️ Could not rename image: {e}")

            # Create BillItem entries
            for item_data in data.get("items", []):
                try:
                    item_ref = get_or_create_item_name(item_data.get("name_normalized", ""))
                    unit_ref = get_or_create_unit(item_data.get("unit", ""))
                    BillItem.objects.create(
                        bill=obj,
                        item_name=item_ref,
                        item_name_raw=item_data.get("name_raw", ""),
                        unit=unit_ref,
                        unit_raw=item_data.get("unit", ""),
                        quantity=item_data.get("quantity", 1),
                        price=item_data.get("price", 0),
                    )
                except Exception as e:
                    print(f"⚠️ Error saving BillItem: {e}")
                    continue

            obj.processed = True
            obj.save()


    def view_image(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="max-height:150px;"/>', obj.image.url)
        return "-"
    view_image.short_description = "Bill Image"
'''

@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = (
        "store",
        "store_name_raw",
        "bill_date",
        "purchase_category",
        "total_amount",
        "processed",
        "uploaded_at",
    )
    readonly_fields = ("processed", "created_at", "modified_at", "view_image")
    ordering = ("-created_at",)
    inlines = [BillItemInline]
    change_list_template = "admin/bills/bill_changelist.html"

    # ----------------------------
    # CUSTOM ADMIN UPLOAD BUTTON
    # ----------------------------
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path("upload-bill/", self.admin_site.admin_view(self.upload_bill_view), name="bills_bill_upload"),
        ]
        return custom_urls + urls

    def upload_bill_view(self, request):
        """Custom view for uploading and processing a bill photo."""
        if request.method == "POST":
            uploaded_file = request.FILES.get("image")
            if not uploaded_file:
                messages.error(request, "Please choose a file to upload.")
                return redirect("..")

            # Step 1️⃣ — Create a placeholder Bill
            bill = Bill.objects.create(
                id=uuid.uuid4(),
                uploaded_at=timezone.now(),
                image=uploaded_file,
                processed=False,
            )

            try:
                # Step 2️⃣ — Process image using Gemini
                data = process_bill_image(bill.image.path)

                # Step 3️⃣ — Update Bill fields
                bill.store = data.get("store")
                bill.store_name_raw = data.get("store_name_raw", "")
                bill.store_name_normalized = data.get("store_name_normalized", "")
                bill.bill_date = data.get("bill_date")
                bill.purchase_category = data.get("purchase_category")
                bill.total_amount = data.get("total_amount", 0)
                bill.save()

                # Step 4️⃣ — Rename image file (storeName_timestamp.ext)
                try:
                    old_path = bill.image.path
                    store_name = bill.store_name_normalized or bill.store_name_raw or "store"
                    store_name = store_name.replace(" ", "_").replace("/", "_")
                    timestamp = (
                        bill.bill_date.strftime("%Y%m%d_%H%M%S")
                        if bill.bill_date
                        else datetime.now().strftime("%Y%m%d_%H%M%S")
                    )
                    ext = os.path.splitext(old_path)[1] or ".jpg"
                    new_filename = f"{store_name}_{timestamp}{ext}"

                    upload_dir = os.path.dirname(old_path)
                    new_path = os.path.join(upload_dir, new_filename)
                    os.rename(old_path, new_path)

                    relative_path = os.path.relpath(new_path, default_storage.location)
                    bill.image.name = relative_path
                    bill.save()
                    print(f"✅ Renamed bill image to {new_filename}")
                except Exception as e:
                    print(f"⚠️ Could not rename image: {e}")

                # Step 5️⃣ — Create BillItem entries
                from .models import BillItem
                from .utils import (
                    get_or_create_item_name,
                    get_or_create_unit,
                    get_or_create_brand,
                )

                for item_data in data.get("items", []):
                    try:
                        item_ref = item_data.get("item_ref")
                        unit_ref = item_data.get("unit_ref")
                        brand_ref = item_data.get("brand_ref")

                        # --- Fallback if any are missing (defensive handling) ---
                        if not item_ref:
                            item_ref = get_or_create_item_name(
                                item_data.get("name_raw", ""),
                                item_data.get("name_normalized", ""),
                            )
                        if not unit_ref:
                            unit_ref = get_or_create_unit(item_data.get("unit", ""))
                        if not brand_ref:
                            brand_ref = get_or_create_brand(
                                item_data.get("brand_raw", ""),
                                item_data.get("brand_normalized", ""),
                            )

                        # --- Create BillItem ---
                        BillItem.objects.create(
                            bill=bill,
                            item_name=item_ref,
                            item_name_raw=item_data.get("name_raw", ""),
                            unit=unit_ref,
                            unit_raw=item_data.get("unit", ""),
                            quantity=item_data.get("quantity", 1),
                            price=item_data.get("price", 0),
                        )
                    except Exception as e:
                        print(f"⚠️ Error saving BillItem: {e}")
                        continue

                # Step 6️⃣ — Finalize
                bill.processed = True
                bill.save()
                messages.success(request, f"✅ Bill '{bill.store_name_raw or bill.store}' processed successfully.")

            except Exception as e:
                messages.error(request, f"⚠️ Error processing bill: {e}")
                bill.delete()
                return redirect("..")

            return redirect("..")

        # Step 7️⃣ — GET: Render upload form
        context = dict(
            self.admin_site.each_context(request),
            title="Upload Bill Image",
        )
        return render(request, "admin/bills/upload_bill.html", context)
    
    #----------------------------
    # INLINE IMAGE PREVIEW
    # ----------------------------
    def view_image(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="max-height:150px;"/>', obj.image.url)
        return "-"
    view_image.short_description = "Bill Image"

# ------------------------------
# BILL ITEM ADMIN
# ------------------------------
@admin.register(BillItem)
class BillItemAdmin(admin.ModelAdmin):
    list_display = (
        "bill",
        "item_name",
        "item_name_raw",
        "unit",
        "unit_raw",
        "quantity",
        "price",
        "created_at",
    )
    readonly_fields = ("created_at", "modified_at")
