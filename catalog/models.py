from django.db import models
from django.utils import timezone
import ai

from common.models import Currency
from user.models import BaseUserManager, BaseUserQuerySet, BaseUserModel
from common.logging_config import logger
from django.forms.models import model_to_dict
import requests
from django.core.files.base import ContentFile



# ============================================================
# Institution
# ============================================================
class InstitutionQuerySet(BaseUserQuerySet):
    def create(self, **kwargs):
        status, existing, data = self.model._prepare_institution_create(**kwargs)

        if status == "skip":
            logger.info("[InstitutionQuerySet.create] Skipped creation for 'cash'")
            return None

        if status == "existing" and existing:
            if data:
                type(self).model.objects.filter(pk=existing.pk).update(**data)
                existing.refresh_from_db()
                logger.debug(f"[InstitutionQuerySet.create] Updated existing Institution: {existing}")
            return existing

        # 1️⃣ Create the DB row first
        logger.debug(f"[InstitutionQuerySet.create] Creating new Institution with data: {data}")
        instance = super().create(**data)

        # 2️⃣ Then attach logo if present
        if "_logo_content" in data:
            try:
                instance.logo.save(data["_logo_name"], data["_logo_content"])
                instance.save(update_fields=["logo"])
                logger.info(f"[InstitutionQuerySet.create] Logo saved for {instance.short_name}")
            except Exception as e:
                logger.warning(
                    f"[InstitutionQuerySet.create] Could not save logo for {instance.short_name}: {e}",
                    exc_info=True,
                )

        return instance



class InstitutionManager(BaseUserManager.from_queryset(InstitutionQuerySet)):
    """Attach custom queryset logic to the manager."""
    pass


class Institution(BaseUserModel):
    """
    Represents a financial or commercial institution such as a bank,
    credit card company, investment platform, or insurance provider.
    """

    name = models.CharField(max_length=100)
    short_name = models.CharField(max_length=50, unique=True)
    type = models.CharField(
        max_length=30,
        choices=[
            ("bank", "Bank"),
            ("credit_card", "Credit Card Issuer"),
            ("broker", "Investment / Brokerage"),
            ("insurance", "Insurance"),
            ("fintech", "Fintech / Wallet"),
            ("other", "Other"),
        ],
        default="bank",
    )
    country = models.CharField(max_length=50, blank=True, null=True)
    website = models.URLField(blank=True, null=True)
    logo = models.ImageField(upload_to="institutions/logos/", blank=True, null=True)

    preferred = models.ForeignKey(
        "self", related_name="variants", on_delete=models.SET_NULL, null=True, blank=True
    )

    objects = InstitutionManager()

    @classmethod
    def _prepare_institution_create(cls, **kwargs):
        func_name = f"{cls.__name__}._prepare_institution_create"

        if kwargs.pop("_skip_prepare", False):  # optional guard if you later set it
            return ("new", None, kwargs)

        ai_checked = kwargs.pop("is_deleted", None)
        short_name = (kwargs.get("short_name") or "").strip()
        country    = (kwargs.get("country") or "").strip()

        if not ai_checked and short_name:
            logger.debug(f"[{func_name}] AI enrichment triggered for '{short_name}'")

            existing_institutions = list(cls.objects.values_list("name", flat=True))
            try:
                query_key = f"{short_name}, {country}" if country else short_name
                ai_lookup = ai.utils.get_institution_data([query_key], existing_institutions)
            except Exception:
                logger.exception(f"[{func_name}] AI lookup failed for '{short_name}'")
                ai_lookup = {}

            ai_info = ai_lookup.get(query_key) or ai_lookup.get(short_name) or {}

            if short_name.lower() == "cash":
                logger.info(f"[{func_name}] Skipping 'cash' institution creation")
                existing = cls.objects.filter(short_name__iexact="cash").first()
                return ("existing", existing, {}) if existing else ("skip", None, {})

            # Fill AI-enriched defaults (don’t .title() empty strings)
            def _title_or(val, fallback):
                s = (val or "").strip()
                return s.title() if s else fallback

            kwargs["name"]       = _title_or(ai_info.get("name"), short_name[:50].title())
            kwargs["short_name"] = _title_or(ai_info.get("short_name"), short_name[:50].title())
            kwargs["type"]       = (ai_info.get("type") or "other").strip().lower()
            kwargs["country"]    = (ai_info.get("country") or "Unknown").strip() or "Unknown"
            kwargs["website"]    = (ai_info.get("website") or None)
            logo_url = ai_info.get("logo_url") or ai_info.get("logo") or None
            if logo_url:
                try:
                    # Only download if not already attached to an existing record
                    existing_logo_check = cls.objects.filter(short_name__iexact=kwargs["short_name"]).first()
                    need_logo = not existing_logo_check or not getattr(existing_logo_check, "logo", None)

                    if need_logo:
                        logger.debug(f"[{func_name}] Fetching logo for '{kwargs['short_name']}': {logo_url}")
                        resp = requests.get(logo_url, timeout=10, stream=True)
                        content_type = resp.headers.get("content-type", "")
                        if resp.status_code == 200 and content_type.startswith("image"):
                            ext = content_type.split("/")[-1].split(";")[0]
                            if len(ext) > 4 or not ext.isalpha():
                                ext = "png"
                            file_name = f"{kwargs['short_name'].replace(' ', '_')}.{ext}"
                            # store temporarily in kwargs for save/create
                            kwargs["_logo_content"] = ContentFile(resp.content)
                            kwargs["_logo_name"] = file_name
                            logger.info(f"[{func_name}] Downloaded logo for '{kwargs['short_name']}'")
                        else:
                            logger.warning(
                                f"[{func_name}] Skipped logo for '{kwargs['short_name']}': "
                                f"invalid response ({resp.status_code}, {content_type})"
                            )
                except Exception as e:
                    logger.warning(f"[{func_name}] Could not fetch logo for '{kwargs['short_name']}': {e}", exc_info=True)

            # Deduplicate by short_name (case-insensitive)
            existing = cls.objects.filter(short_name__iexact=kwargs["short_name"]).first()
            if existing:
                updated_fields = {}
                for key, value in kwargs.items():
                    if hasattr(existing, key) and value not in (None, ""):
                        if getattr(existing, key) != value:
                            updated_fields[key] = value
                logger.info(f"[{func_name}] Existing institution found: {existing}, updated_fields={updated_fields}")
                return ("existing", existing, updated_fields)

        return ("new", None, kwargs)

    def save(self, *args, **kwargs):
        func_name = f"{self.__class__.__name__}.save"
        try:
            data = model_to_dict(self, fields=[f.name for f in self._meta.fields])
            status, existing, updates = self.__class__._prepare_institution_create(**data)

            if status == "skip":
                logger.info(f"[{func_name}] Skipped saving 'cash'")
                return

            if status == "existing" and existing:
                if updates:
                    self.__class__.objects.filter(pk=existing.pk).update(**updates)
                    existing.refresh_from_db()
                    logger.debug(f"[{func_name}] Updated existing Institution: {existing}")
                self.pk = existing.pk
                return

            # new instance → set enriched fields then save
            for k, v in updates.items():
                setattr(self, k, v)
            super().save(*args, **kwargs)
            logger.debug(f"[{func_name}] Saved new Institution: {self}")
            if "_logo_content" in updates:
                try:
                    self.logo.save(updates["_logo_name"], updates["_logo_content"])
                    super().save(update_fields=["logo"])
                    logger.info(f"[{func_name}] Logo saved for {self.short_name}")
                except Exception as e:
                    logger.warning(f"[{func_name}] Could not save logo for {self.short_name}: {e}", exc_info=True)

        except Exception as e:
            logger.exception(f"[{func_name}] Error during save operation")
            raise e

    def canonical(self):
        return self.preferred or self

    def __str__(self):
        return self.short_name or self.name


# ============================================================
# Categories
# ============================================================

class CategoryGroup(BaseUserModel):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name


class PurchaseCategory(BaseUserModel):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    group = models.ForeignKey(
        CategoryGroup,
        related_name="categories",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )

    def canonical(self):
        return self

    def __str__(self):
        group_name = self.group.name if self.group else ""
        return f"{self.name} ({group_name})" if group_name else self.name


# ============================================================
# Brand / Product
# ============================================================

class Brand(BaseUserModel):
    name = models.CharField(max_length=255, unique=True)
    preferred = models.ForeignKey(
        "self",
        related_name="variants",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    def canonical(self):
        return self.preferred or self

    def __str__(self):
        return self.name


class Product(BaseUserModel):
    name = models.CharField(max_length=255, unique=True)
    preferred = models.ForeignKey(
        "self",
        related_name="variants",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    brand = models.ForeignKey(
        "catalog.Brand",
        related_name="items",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    preferred_unit = models.ForeignKey(
        "common.Unit",
        related_name="default_for_items",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    category = models.ForeignKey(
        PurchaseCategory,
        related_name="products",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    def canonical(self):
        return self.preferred or self

    def get_preferred_unit(self):
        if self.preferred_unit:
            return self.preferred_unit
        if self.preferred and self.preferred.preferred_unit:
            return self.preferred.preferred_unit
        return None

    def __str__(self):
        label = self.name
        if self.preferred:
            label += f" → {self.preferred.name}"
            category = self.preferred.category
        else:
            category = self.category

        if category:
            label += f" ({category.name})"
        return label


# ============================================================
# Store
# ============================================================

class Store(BaseUserModel):
    name = models.CharField(max_length=255, unique=True)
    preferred = models.ForeignKey(
        "self",
        related_name="variants",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    categories = models.ManyToManyField(
        PurchaseCategory, related_name="stores", blank=True
    )

    def canonical(self):
        return self.preferred or self

    def __str__(self):
        try:
            # Prefer preferred.name if available
            if self.preferred_id:
                label = getattr(self.preferred, "name", "(unnamed)")
                # Only access categories if preferred is saved
                if self.preferred_id:
                    cats_qs = getattr(self.preferred, "categories", None)
                    if cats_qs is not None and self.preferred.pk:
                        cats = list(cats_qs.all()[:2])
                        if cats:
                            label += " (" + ", ".join(c.name for c in cats) + ")"
            else:
                label = self.name or "(unnamed)"
                if self.pk:  # Only safe after save
                    cats_qs = getattr(self, "categories", None)
                    if cats_qs is not None:
                        cats = list(cats_qs.all()[:2])
                        if cats:
                            label += " (" + ", ".join(c.name for c in cats) + ")"
            return label
        except Exception:
            # Fallback if anything goes wrong during saving/logging
            return getattr(self, "name", "(unsaved)")


# ============================================================
# Exchange Rate
# ============================================================

class ExchangeRateRecord(BaseUserModel):
    """
    Immutable record of an exchange rate used during a transfer or cross-currency transaction.
    Stored as metadata inside Transaction (no reverse relation).
    """
    base_currency = models.ForeignKey(
        Currency,
        related_name="base_exchange_records",
        on_delete=models.PROTECT,
        help_text="Currency being converted from",
    )
    quote_currency = models.ForeignKey(
        Currency,
        related_name="quoted_exchange_records",
        on_delete=models.PROTECT,
        help_text="Currency being converted to",
    )
    market_rate = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        help_text="Mid-market rate at the time (e.g. ECB or CoinGecko)",
        null=True,
        blank=True,
    )
    provider_rate = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        help_text="Actual rate used by the institution performing the conversion",
    )
    provider = models.ForeignKey(
        Institution,
        related_name="+",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Institution or service provider that executed the exchange (e.g. Revolut, Wise, Binance)",
    )
    fee_percent = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        default=0,
        help_text="Markup percentage between market and provider rate",
    )
    date = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        base = getattr(self.base_currency, "code", str(self.base_currency))
        quote = getattr(self.quote_currency, "code", str(self.quote_currency))
        provider_name = self.provider.name if self.provider else "Unknown"
        return f"1 {quote} = {self.provider_rate} {base} ({provider_name})"
