from django import forms
from django.forms import BaseInlineFormSet
from decimal import Decimal
from account.models import Account
from common.models import Currency, Unit
from transaction.models import Transaction, TransactionItem, TransactionSplit
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
        help_text="Transaction fee (optional). A separate fee transaction will be created automatically."
    )
    to_amount = forms.DecimalField(
        required=False,
        decimal_places=2,
        max_digits=12,
        label="To amount",
    )
    transaction_currency_amount = forms.DecimalField(
        required=False,
        decimal_places=2,
        max_digits=12,
        label="Transaction amount",
        help_text="Shows the transaction amount in transaction currency. This is calculated from the account amount and exchange rate."
    )
    exchange_rate = forms.DecimalField(
        required=False,
        decimal_places=8,
        max_digits=20,
        label="Exchange rate (optional)",
        help_text="Manual exchange rate (X account_currency = transaction_currency). If not provided, will be calculated from amounts or fetched from market."
    )
    
    split_method = forms.ChoiceField(
        choices=[
            ('equally', 'Equally'),
            ('unequally', 'Unequally (Manual Amount)'),
            ('percentage', 'By Percentage'),
            ('shares', 'By Shares'),
        ],
        required=False,
        initial='equally',
        label="Split Method",
        help_text="How to split this transaction among friends (applies to all splits)"
    )

    class Meta:
        model = Transaction
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        # Capture the request (admin passes it through `get_form` or formfield_for_* methods)
        instance = kwargs.get("instance")
        super().__init__(*args, **kwargs)
        request = getattr(self, 'request', None)

        # If we have access to the request, limit account choices
        if request and request.user.is_authenticated:
            self.fields["to_account"].queryset = Account.objects.filter(created_by=request.user)
        else:
            # fallback (in case request is missing)
            self.fields["to_account"].queryset = Account.objects.none()

        instance = kwargs.get("instance")
        
        # Prefill split_method from existing splits or default to 'equally'
        if instance and instance.pk:
            first_split = instance.splits.filter(is_deleted=False).first()
            if first_split and first_split.notes and isinstance(first_split.notes, dict):
                split_method = first_split.notes.get('split_method', 'equally')
                if not self.initial.get("split_method"):
                    self.fields["split_method"].initial = split_method
                    self.initial["split_method"] = split_method
        else:
            # New transaction, default to 'equally'
            if not self.initial.get("split_method"):
                self.fields["split_method"].initial = 'equally'
                self.initial["split_method"] = 'equally'
        
        # Prefill "fee_amount" for any transaction with a fee
        if instance and instance.fee and not self.initial.get("fee_amount"):
            self.fields["fee_amount"].initial = instance.fee.amount
        
        # Prefill exchange rate fields for cross-currency transactions
        if instance and instance.exchange_rate_record:
            exch = instance.exchange_rate_record
            # If transaction currency is different from account currency, show the exchange rate
            account_currency = getattr(instance.account, "currency", None) if instance.account else None
            if account_currency and instance.currency and account_currency != instance.currency:
                # Set exchange rate from the exchange rate record first
                if not self.initial.get("exchange_rate"):
                    self.fields["exchange_rate"].initial = exch.provider_rate
                    self.initial["exchange_rate"] = exch.provider_rate
                
                # Calculate transaction currency amount from account amount and exchange rate
                # This calculation happens in Python, not JavaScript
                if exch.provider_rate and instance.amount:
                    try:
                        from decimal import Decimal
                        # transaction_amount = account_amount / exchange_rate
                        # exchange_rate is: X account_currency = transaction_currency
                        # So: transaction_amount = account_amount / X
                        transaction_amount = Decimal(str(instance.amount)) / Decimal(str(exch.provider_rate))
                        calculated_value = float(transaction_amount.quantize(Decimal("0.01")))
                        
                        # Set the initial value which will be displayed in the form
                        self.fields["transaction_currency_amount"].initial = calculated_value
                        # Also set it in self.initial dict to ensure it's pre-filled
                        self.initial["transaction_currency_amount"] = calculated_value
                        # Set it as a data attribute on the widget for JavaScript access
                        if 'data-initial-value' not in self.fields["transaction_currency_amount"].widget.attrs:
                            self.fields["transaction_currency_amount"].widget.attrs['data-initial-value'] = str(calculated_value)
                        
                        logger.debug(
                            f"[TransactionForm.__init__] Calculated transaction currency amount: "
                            f"{calculated_value} from account amount {instance.amount} / exchange rate {exch.provider_rate}"
                        )
                    except Exception as e:
                        logger.warning(f"[TransactionForm.__init__] Error calculating transaction currency amount: {e}", exc_info=True)
                        pass
                
                # Make transaction_currency_amount readonly AFTER setting the value
                # This ensures the value is set before making it readonly
                self.fields["transaction_currency_amount"].widget.attrs['readonly'] = True
                self.fields["transaction_currency_amount"].widget.attrs['class'] = 'readonly'
                self.fields["transaction_currency_amount"].required = False
        
        if instance and instance.linked_transaction_id:
            linked = instance.linked_transaction

            # Prefill "to_account"
            if linked.account_id:
                self.fields["to_account"].initial = linked.account

            # Prefill "to_amount"
            if linked.amount:
                self.fields["to_amount"].initial = linked.amount

            # Prefill "fee_amount" from linked transaction if not already set
            if linked.fee and not self.initial.get("fee_amount") and not instance.fee:
                self.fields["fee_amount"].initial = linked.fee.amount


class TransactionSplitFormSet(BaseInlineFormSet):
    """Custom formset for TransactionSplit with validation."""
    
    def save(self, commit=True):
        """Override save to handle existing splits (including deleted ones)."""
        from transaction.models import TransactionSplit
        
        transaction = self.instance
        if not transaction or not transaction.pk:
            # New transaction - just use parent save
            return super().save(commit=commit)
        
        # Get all forms that are not marked for deletion
        forms_to_save = [f for f in self.forms if f.cleaned_data and not f.cleaned_data.get("DELETE", False)]
        
        # Track which users we've processed to avoid duplicates within the formset
        processed_users = set()
        
        # Before parent save, link existing splits to forms to avoid duplicates
        for form in forms_to_save:
            user = form.cleaned_data.get("user")
            if not user:
                continue
            
            # Check for duplicate within the formset itself
            if user in processed_users:
                # Mark this form for deletion to skip it
                form.cleaned_data['DELETE'] = True
                continue
            processed_users.add(user)
            
            # Check if a split already exists for this transaction and user (including deleted)
            existing_split = TransactionSplit.all_objects.filter(
                transaction=transaction,
                user=user
            ).first()
            
            if existing_split:
                # If it exists (even if deleted), restore and link it to the form
                if existing_split.is_deleted:
                    existing_split.is_deleted = False
                
                # Link the form instance to the existing split
                # This way parent save will update it instead of creating a new one
                form.instance = existing_split
                form.instance.pk = existing_split.pk
                
                # Update fields from cleaned_data before save
                for field_name, value in form.cleaned_data.items():
                    if field_name not in ['DELETE', 'id', 'split_value'] and hasattr(form.instance, field_name):
                        setattr(form.instance, field_name, value)
        
        # Now call parent save - it will handle everything correctly
        # including setting new_objects, changed_objects, deleted_objects
        return super().save(commit=commit)
    
    def clean(self):
        """Validate that total of split amounts equals transaction amount and no duplicate users."""
        errors = []
        try:
            super().clean()
        except forms.ValidationError as e:
            errors.extend(e.error_list)
        
        # Only validate if we have a transaction instance
        if not self.instance:
            if errors:
                raise forms.ValidationError(errors)
            return
        
        # Check for duplicate users within the formset (not in database - that's handled in save)
        # This prevents the same user from appearing in multiple rows in the same form
        seen_users = {}
        for i, form in enumerate(self.forms):
            if form.cleaned_data and not form.cleaned_data.get("DELETE", False):
                user = form.cleaned_data.get("user")
                if user:
                    if user in seen_users:
                        # Found duplicate user within the formset
                        other_form_index = seen_users[user]
                        errors.append(
                            forms.ValidationError(
                                f"Duplicate user: {user.email if hasattr(user, 'email') else user} appears in multiple split rows. "
                                f"Each user can only have one split per transaction."
                            )
                        )
                        # Mark both forms as having errors
                        form.add_error('user', f"This user already appears in another split row.")
                        if other_form_index is not None:
                            self.forms[other_form_index].add_error('user', f"This user already appears in another split row.")
                    else:
                        seen_users[user] = i
        
        # Get transaction amount - use the amount from the instance
        # For new transactions, the amount should be set in the main form
        transaction_amount = Decimal(str(self.instance.amount or 0))
        if transaction_amount == 0:
            # No validation needed if transaction amount is 0
            if errors:
                raise forms.ValidationError(errors)
            return
        
        # Calculate total of all split amounts (excluding deleted ones)
        total_split_amount = Decimal("0")
        valid_splits_count = 0
        
        for form in self.forms:
            if form.cleaned_data and not form.cleaned_data.get("DELETE", False):
                amount = form.cleaned_data.get("amount")
                if amount is not None:
                    try:
                        total_split_amount += Decimal(str(amount))
                        valid_splits_count += 1
                    except (ValueError, TypeError):
                        # Skip invalid amounts
                        pass
        
        # Only validate if there are splits
        if valid_splits_count > 0:
            # Allow small tolerance for rounding errors (0.02)
            tolerance = Decimal("0.02")
            difference = abs(total_split_amount - transaction_amount)
            
            if difference > tolerance:
                errors.append(
                    forms.ValidationError(
                        f"Total of split amounts ({total_split_amount:.2f}) must equal transaction amount ({transaction_amount:.2f}). "
                        f"Difference: {difference:.2f}"
                    )
                )
        
        if errors:
            raise forms.ValidationError(errors)
