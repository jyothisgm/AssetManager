from django import forms
from transaction.models import TransactionItem
from catalog.models import Brand, PurchaseCategory


class TransactionItemInlineForm(forms.ModelForm):
    brand_display = forms.ModelChoiceField(
        queryset=Brand.objects.all(),
        required=False,
        label="Brand"
    )
    category_display = forms.ModelChoiceField(
        queryset=PurchaseCategory.objects.all(),
        required=False,
        label="Category"
    )

    class Meta:
        model = TransactionItem
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.product:
            self.fields["brand_display"].initial = self.instance.product.brand
            # Try both product.category and product.preferred.category
            cat = getattr(self.instance.product, "category", None)
            if not cat and getattr(self.instance.product, "preferred", None):
                cat = getattr(self.instance.product.preferred, "category", None)
            self.fields["category_display"].initial = cat

    def save(self, commit=True):
        instance = super().save(commit=False)
        product = instance.product

        # Update product.brand if changed
        brand = self.cleaned_data.get("brand_display")
        category = self.cleaned_data.get("category_display")
        if product:
            if brand and product.brand != brand:
                product.brand = brand
            if category and hasattr(product, "category"):
                product.category = category
            elif category and hasattr(product, "preferred") and hasattr(product.preferred, "category"):
                product.preferred.category = category
            if commit:
                product.save()

        if commit:
            instance.save()
        return instance
