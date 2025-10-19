from django.db import models
from django.utils import timezone
from django.core.files.storage import FileSystemStorage
import uuid

bill_storage = FileSystemStorage(location='media/bills', base_url='/media/bills/')


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Unit(TimeStampedModel):
    """
    Canonicalized measurement units for weight, length, volume, and pieces,
    including conversion relationships.
    """
    CATEGORY_CHOICES = [
        ("weight", "Weight"),
        ("length", "Length"),
        ("volume", "Volume"),
        ("pieces", "Pieces"),
    ]

    name = models.CharField(max_length=50, unique=True)
    symbol = models.CharField(max_length=10, blank=True, null=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)

    preferred = models.ForeignKey(
        "self", related_name="variants", on_delete=models.SET_NULL, null=True, blank=True
    )
    base_unit = models.ForeignKey(
        "self", related_name="derived_units", on_delete=models.SET_NULL, null=True, blank=True,
        help_text="Base or canonical unit for this measurement type (e.g. g, m, L, pcs)."
    )
    conversion_to_base = models.FloatField(
        null=True, blank=True,
        help_text="Multiply by this factor to convert to base unit. (1 if itself is base)"
    )

    def canonical(self):
        return self.preferred or self

    def __str__(self):
        base = f" (1 {self.symbol or self.name} = {self.conversion_to_base or 1} {self.base_unit.symbol if self.base_unit else self.symbol})"
        label = f"{self.name} ({self.symbol or ''})"
        if self.preferred:
            label += f" → {self.preferred.name}"
        return label + base


class CategoryGroup(TimeStampedModel):
    """
    Represents high-level groupings of purchase categories,
    like Essentials, Lifestyle, Utilities, Food & Beverage, etc.
    """
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name


class PurchaseCategory(TimeStampedModel):
    """
    Represents a purchase or store category (e.g., Groceries, Electronics, Restaurants),
    which can belong to multiple CategoryGroups.
    """
    name = models.CharField(max_length=100, unique=True)
    preferred = models.ForeignKey(
        "self", related_name="variants", on_delete=models.SET_NULL, null=True, blank=True
    )
    description = models.TextField(blank=True, null=True)

    # ✅ many-to-many link instead of single ForeignKey
    groups = models.ManyToManyField(CategoryGroup, related_name="categories", blank=True)

    def canonical(self):
        return self.preferred or self

    def __str__(self):
        group_names = ", ".join(g.name for g in self.groups.all()) if self.pk else ""
        label = f"{self.name}"
        if group_names:
            label += f" ({group_names})"
        if self.preferred:
            label += f" → {self.preferred.name}"
        return label


class Store(TimeStampedModel):
    name = models.CharField(max_length=255, unique=True)
    preferred = models.ForeignKey("self", related_name="variants", on_delete=models.SET_NULL, null=True, blank=True)
    category = models.ForeignKey(
        "PurchaseCategory", related_name="stores", on_delete=models.SET_NULL, null=True, blank=True
    )

    def canonical(self):
        return self.preferred or self

    def __str__(self):
        label = self.preferred.name if self.preferred else self.name
        if self.category:
            group_names = ", ".join(g.name for g in self.category.groups.all())
            return f"{label} ({self.category.name}{' - ' + group_names if group_names else ''})"
        return label


class Brand(TimeStampedModel):
    """
    Represents a company or product brand, e.g., 'Coca Cola', 'Nestlé', 'Jumbo'.
    Multiple ItemNames can belong to one Brand.
    """
    name = models.CharField(max_length=255, unique=True)
    preferred = models.ForeignKey(
        "self",
        related_name="variants",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="If this is a variant spelling, link to the canonical brand.",
    )

    def canonical(self):
        return self.preferred or self

    def __str__(self):
        return self.name


class ItemName(TimeStampedModel):
    """
    Represents one product/item name variant.
    Many variants can share one canonical preferred entry.
    """
    name = models.CharField(max_length=255, unique=True)
    preferred = models.ForeignKey(
        "self", related_name="variants", on_delete=models.SET_NULL, null=True, blank=True
    )
    brand = models.ForeignKey(
        "Brand",
        related_name="items",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="The brand this item belongs to, if applicable."
    )
    preferred_unit = models.ForeignKey(
        "Unit",
        related_name="default_for_items",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Default or most common unit for this item (e.g. grams, liters, pieces)."
    )


    def canonical(self):
        return self.preferred or self
    
    def get_preferred_unit(self):
        """
        Return this item's preferred unit,
        falling back to its canonical's preferred unit if not set.
        """
        if self.preferred_unit:
            return self.preferred_unit
        if self.preferred and self.preferred.preferred_unit:
            return self.preferred.preferred_unit
        return None


    def __str__(self):
        return f"{self.name}" + (f" → {self.preferred.name}" if self.preferred else "")


# ------------------------------
# Bill and BillItem
# ------------------------------
from django.db import models
from django.utils import timezone
import uuid

class Bill(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    uploaded_at = models.DateTimeField(default=timezone.now)
    image = models.ImageField(upload_to="", storage=bill_storage)
    processed = models.BooleanField(default=False)

    store = models.ForeignKey(
        Store,
        related_name="bills",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    store_name_raw = models.CharField(max_length=255, blank=True, null=True)

    bill_date = models.DateTimeField(blank=True, null=True)

    # ✅ changed from CharField to ForeignKey
    purchase_category = models.ForeignKey(
        "PurchaseCategory",
        related_name="bills",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    total_amount = models.FloatField(blank=True, null=True)

    def __str__(self):
        store_name = self.store.canonical().name if self.store else self.store_name_raw or "Bill"
        category = self.purchase_category.name if self.purchase_category else "Uncategorized"
        date_display = self.bill_date or self.uploaded_at
        return f"{store_name} - {category} ({date_display.date()})"



class BillItem(TimeStampedModel):
    bill = models.ForeignKey(Bill, related_name="items", on_delete=models.CASCADE)
    item_name = models.ForeignKey(ItemName, related_name="bill_items", on_delete=models.SET_NULL, null=True, blank=True)
    item_name_raw = models.CharField(max_length=255)

    quantity = models.FloatField(default=1)
    unit = models.ForeignKey(Unit, related_name="bill_items", on_delete=models.SET_NULL, null=True, blank=True)
    unit_raw = models.CharField(max_length=20, blank=True, null=True)  # ✅ Add this line

    price = models.FloatField()

    def __str__(self):
        canonical = self.item_name.canonical().name if self.item_name else self.item_name_raw
        return f"{canonical} ({self.quantity} {self.unit or ''}) - ₹{self.price}"
