from django import forms
from account.models import Account
from common.models import Currency, Unit
from transaction.models import Transaction, TransactionItem
from catalog.models import Brand, Product, PurchaseCategory, Store
from common.logging_config import logger
from dal import autocomplete


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
        func_name = f"{self.__class__.__name__}.__init__"
        try:
            super().__init__(*args, **kwargs)
            instance = getattr(self, "instance", None)
            if instance and instance.product:
                logger.debug(f"[{func_name}] Initializing form for TransactionItem ID={instance.id} (product={instance.product})")

                # Prefill brand
                self.fields["brand_display"].initial = instance.product.brand

                # Prefill category (try product or preferred product)
                cat = getattr(instance.product, "category", None)
                if not cat and getattr(instance.product, "preferred", None):
                    cat = getattr(instance.product.preferred, "category", None)
                self.fields["category_display"].initial = cat
                self.fields["unit"].label_from_instance = lambda obj: obj.symbol or obj.name
                logger.debug(f"[{func_name}] Set initial brand={instance.product.brand}, category={cat}")
        except Exception as e:
            logger.warning(f"[{func_name}] Error initializing form for TransactionItem", exc_info=True)
            raise e

    def save(self, commit=True):
        func_name = f"{self.__class__.__name__}.save"
        try:
            instance = super().save(commit=False)
            product = instance.product
            brand = self.cleaned_data.get("brand_display")
            category = self.cleaned_data.get("category_display")

            logger.debug(f"[{func_name}] Saving TransactionItem ID={getattr(instance, 'id', None)} | Product={product} | Brand={brand} | Category={category}")

            if product:
                # Brand update
                if brand and product.brand != brand:
                    logger.info(f"[{func_name}] Updating product brand: {product.brand} → {brand}")
                    product.brand = brand

                # Category update
                if category:
                    if hasattr(product, "category"):
                        product.category = category
                        logger.info(f"[{func_name}] Updating product category: {category}")
                    elif hasattr(product, "preferred") and hasattr(product.preferred, "category"):
                        product.preferred.category = category
                        logger.info(f"[{func_name}] Updating preferred product category: {category}")

                if commit:
                    product.save()
                    logger.debug(f"[{func_name}] Product saved for TransactionItem ID={getattr(instance, 'id', None)}")

            if commit:
                instance.save()
                logger.debug(f"[{func_name}] TransactionItem saved successfully (ID={instance.id})")

            return instance
        except Exception as e:
            logger.warning(f"[{func_name}] Error saving TransactionItem", exc_info=True)
            raise e


class BulkEditTransactionForm(forms.Form):
    """Form for bulk editing multiple Transactions with DAL searchable fields."""
    transaction_type = forms.ChoiceField(
        choices=[("", "----")] + Transaction.TRANSACTION_TYPES,
        required=False,
        label="Transaction Type",
    )

    currency = forms.ModelChoiceField(
        queryset=Currency.objects.none(),
        required=False,
        label="Currency",
        widget=autocomplete.ModelSelect2(
            url="currency-autocomplete",
            attrs={"data-placeholder": "Search currency..."},
        ),
    )

    account = forms.ModelChoiceField(
        queryset=Account.objects.none(),
        required=False,
        label="Account",
        widget=autocomplete.ModelSelect2(
            url="account-autocomplete",
            attrs={"data-placeholder": "Search account..."},
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

    store = forms.ModelChoiceField(
        queryset=Store.objects.none(),
        required=False,
        label="Store",
        widget=autocomplete.ModelSelect2(
            url="store-autocomplete",
            attrs={"data-placeholder": "Search store..."},
        ),
    )

    def __init__(self, *args, **kwargs):
        request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)
        # Optionally restrict or reassign if user context needed
        if request:
            self.fields["account"].queryset = Account.objects.filter(created_by=request.user)
            self.fields["store"].queryset = Store.objects.filter(preferred=None)
            self.fields["category"].queryset = PurchaseCategory.objects.all()
            self.fields["currency"].queryset = Currency.objects.all()


class BulkEditTransactionItemForm(forms.Form):
    """Form for bulk editing multiple Transactions with DAL searchable fields."""
    product = forms.ModelChoiceField(
        queryset=Product.objects.none(),
        required=False,
        label="Product",
        widget=autocomplete.ModelSelect2(
            url="product-autocomplete",
            attrs={"data-placeholder": "Search product..."},
        ),
    )

    unit = forms.ModelChoiceField(
        queryset=Unit.objects.none(),
        required=False,
        label="Unit",
        widget=autocomplete.ModelSelect2(
            url="unit-autocomplete",
            attrs={"data-placeholder": "Search Unit..."},
        ),
    )

    def __init__(self, *args, **kwargs):
        request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)
        # Optionally restrict or reassign if user context needed
        if request:
            self.fields["product"].queryset = Product.objects.filter(preferred=None)
            self.fields["unit"].queryset = Unit.objects.filter(preferred=None)


class TransactionForm(forms.ModelForm):
    to_account = forms.ModelChoiceField(
        queryset=Account.objects.none(),
        required=False,
        label="To Account",
        widget=autocomplete.ModelSelect2(
            url="account-autocomplete",
            attrs={
                "data-placeholder": "Search to account…",
            },
        ),
    )
    fee_amount = forms.DecimalField(
        required=False,
        decimal_places=2,
        max_digits=12,
        label="Fee amount",
        help_text="Transfer fee in source currency (optional)."
    )
    to_amount = forms.DecimalField(
        required=False,
        decimal_places=2,
        max_digits=12,
        label="To amount",
    )

    class Meta:
        model = Transaction
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        # Capture the request (admin passes it through `get_form` or formfield_for_* methods)
        super().__init__(*args, **kwargs)
        request = getattr(self, 'request', None)

        # If we have access to the request, limit account choices
        if request and request.user.is_authenticated:
            self.fields["to_account"].queryset = Account.objects.filter(created_by=request.user)
        else:
            # fallback (in case request is missing)
            self.fields["to_account"].queryset = Account.objects.none()

        instance = kwargs.get("instance")
        if instance and instance.linked_transaction_id:
            linked = instance.linked_transaction

            # Prefill "to_account"
            if linked.account_id:
                self.fields["to_account"].initial = linked.account

            # Prefill "to_amount"
            if linked.amount:
                self.fields["to_amount"].initial = linked.amount

            # Prefill "fee_amount"
            if instance.fee and not self.initial.get("fee_amount"):
                self.fields["fee_amount"].initial = instance.fee.amount
            elif linked.fee and not self.initial.get("fee_amount"):
                self.fields["fee_amount"].initial = linked.fee.amount


