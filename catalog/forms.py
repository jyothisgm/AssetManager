from django import forms
from dal import autocomplete

from catalog.models import Brand, Product, Store, PurchaseCategory
from common.models import Unit


# -------------------------------
# BRAND BULK EDIT FORM
# -------------------------------
class BulkEditBrandForm(forms.Form):
    preferred = forms.ModelChoiceField(
        queryset=Brand.objects.none(),
        required=False,
        label="Preferred Brand",
        widget=autocomplete.ModelSelect2(
            url="brand-autocomplete",
            attrs={"data-placeholder": "Search brand..."},
        ),
    )

    def __init__(self, *args, **kwargs):
        request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)
        if request:
            self.fields["preferred"].queryset = Brand.objects.filter(preferred=None)
            

# -------------------------------
# PRODUCT BULK EDIT FORM
# -------------------------------
class BulkEditProductForm(forms.Form):
    preferred = forms.ModelChoiceField(
        queryset=Product.objects.none(),
        required=False,
        label="Preferred Product",
        widget=autocomplete.ModelSelect2(
            url="product-autocomplete",
            attrs={"data-placeholder": "Search preferred product..."},
        ),
    )

    brand = forms.ModelChoiceField(
        queryset=Brand.objects.none(),
        required=False,
        label="Brand",
        widget=autocomplete.ModelSelect2(
            url="brand-autocomplete",
            attrs={"data-placeholder": "Search brand..."},
        ),
    )

    preferred_unit = forms.ModelChoiceField(
        queryset=Unit.objects.none(),
        required=False,
        label="Preferred Unit",
        widget=autocomplete.ModelSelect2(
            url="unit-autocomplete",
            attrs={"data-placeholder": "Search unit..."},
        ),
    )

    category = forms.ModelChoiceField(
        queryset=PurchaseCategory.objects.none(),
        required=False,
        label="Category",
        widget=autocomplete.ModelSelect2(
            url="category-autocomplete",
            attrs={"data-placeholder": "Search category..."},
        ),
    )

    def __init__(self, *args, **kwargs):
        request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)
        if request:
            self.fields["preferred"].queryset = Product.objects.filter(preferred=None)
            self.fields["brand"].queryset = Brand.objects.filter(preferred=None)
            self.fields["preferred_unit"].queryset = Unit.objects.filter(preferred=None)
            self.fields["category"].queryset = PurchaseCategory.objects.all()


# -------------------------------
# STORE BULK EDIT FORM
# -------------------------------
class BulkEditStoreForm(forms.Form):
    preferred = forms.ModelChoiceField(
        queryset=Store.objects.none(),
        required=False,
        label="Preferred Store",
        widget=autocomplete.ModelSelect2(
            url="store-autocomplete",
            attrs={"data-placeholder": "Search preferred store..."},
        ),
    )

    categories = forms.ModelMultipleChoiceField(
        queryset=PurchaseCategory.objects.none(),
        required=False,
        label="Categories",
        widget=autocomplete.ModelSelect2Multiple(
            url="category-autocomplete",
            attrs={"data-placeholder": "Search categories..."},
        ),
    )

    def __init__(self, *args, **kwargs):
        request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)
        if request:
            self.fields["preferred"].queryset = Store.objects.filter(preferred=None)
            self.fields["categories"].queryset = PurchaseCategory.objects.all()
