from django import forms
from transaction.models import TransactionItem
from catalog.models import Brand, PurchaseCategory
from common.logging_config import logger


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
                logger.debug(f"[{func_name}] Set initial brand={instance.product.brand}, category={cat}")
        except Exception as e:
            logger.exception(f"[{func_name}] Error initializing form for TransactionItem")
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
            logger.exception(f"[{func_name}] Error saving TransactionItem")
            raise e
