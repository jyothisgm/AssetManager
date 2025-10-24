import requests
from datetime import date
from django.core.management.base import BaseCommand
from catalog.models import ExchangeRateRecord
from common.logging_config import logger


class Command(BaseCommand):
    help = "Fetch and update exchange rates for all ExchangeRateRecord entries using Frankfurter.dev with Fawaz CDN fallback."

    BASE_URL = "https://api.frankfurter.dev/v1"
    FALLBACK_URL_TEMPLATE = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{date}/v1/currencies/{quote}.json"
    MIN_DATE = date(1999, 1, 4)  # Frankfurter’s earliest available data

    def handle(self, *args, **options):
        logger.info("🚀 [fetch_currency_rate] Starting exchange rate update...")

        records = ExchangeRateRecord.objects.filter(date__gte=self.MIN_DATE)
        total_records = records.count()
        updated, failed = 0, 0

        logger.debug(f"🔍 Found {total_records} records to process (since {self.MIN_DATE})")

        for record in records:
            date_str = record.date.strftime("%Y-%m-%d")
            base = record.base_currency.code.upper()
            quote = record.quote_currency.code.upper()
            url = f"{self.BASE_URL}/{date_str}"
            params = {"from": quote, "to": base}

            try:
                response = requests.get(url, params=params, timeout=10)

                if response.status_code != 200:
                    logger.warning(f"⚠️ [Frankfurter] {response.status_code} for {base}->{quote} ({date_str}), using fallback")
                    rates = self.fetch_from_fawaz(date_str, base, quote)
                else:
                    data = response.json()
                    rates = data.get("rates", {})

                    if not rates:
                        logger.warning(f"⚠️ [Frankfurter] Empty rates for {base}->{quote} on {date_str}, using fallback")
                        rates = self.fetch_from_fawaz(date_str, base, quote)

            except Exception as e:
                logger.warning(f"⚠️ [Frankfurter] Exception fetching {base}->{quote} ({date_str}): {e}, using fallback", exc_info=True)
                rates = self.fetch_from_fawaz(date_str, base, quote)
                failed += 1
                continue

            rate = rates.get(base) or rates.get(base.lower())
            if rate:
                record.market_rate = min(rate, record.provider_rate) if record.provider_rate else rate
                record.save(update_fields=["market_rate"])
                updated += 1
                logger.info(f"✅ [Rate Updated] {date_str} | {base}->{quote} = {rate}")
            else:
                failed += 1
                logger.warning(f"⚠️ [Missing] No rate for {base}->{quote} on {date_str}")

        logger.info(f"🎯 [fetch_currency_rate] Done! Updated {updated}/{total_records} records | Failed: {failed}")

    # ---------------------------------------------------------------------
    # 🔁 Fallback fetcher
    # ---------------------------------------------------------------------
    def fetch_from_fawaz(self, date_str, base, quote):
        """Fetch rates from Fawaz Ahmed’s CDN as fallback."""
        base = base.lower()
        quote = quote.lower()
        url = self.FALLBACK_URL_TEMPLATE.format(date=date_str, quote=quote)

        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if quote in data:
                    return data[quote]
                logger.warning(f"⚠️ [Fallback] No data key found for {base}->{quote} ({date_str})")
                return {}
            else:
                logger.warning(f"⚠️ [Fallback] Failed {base}->{quote} ({response.status_code}) → {url}")
                return {}
        except Exception as e:
            logger.warning(f"⚠️ [Fallback] Exception {base}->{quote}: {e}")
            return {}
