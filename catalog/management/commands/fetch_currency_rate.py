import requests
from collections import defaultdict
from django.core.management.base import BaseCommand
from catalog.models import ExchangeRateRecord
from datetime import date

class Command(BaseCommand):
    help = "Fetch and update exchange rates for all ExchangeRateRecord entries using Frankfurter.dev (v1) with Fawaz CDN fallback."

    BASE_URL = "https://api.frankfurter.dev/v1"
    FALLBACK_URL_TEMPLATE = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{date}/v1/currencies/{quote}.json"
    MIN_DATE = date(1999, 1, 4)  # Frankfurter’s earliest available data

    def handle(self, *args, **options):
        records = ExchangeRateRecord.objects.filter(date__gte=self.MIN_DATE)

        total_records = records.count()
        updated, failed = 0, 0

        for record in records:
            date_str = record.date.strftime("%Y-%m-%d")
            base = record.base_currency.code.upper()
            quote = record.quote_currency.code.upper()
            url = f"{self.BASE_URL}/{date_str}"
            params = {"from": quote, "to": base}

            try:
                response = requests.get(url, params=params, timeout=10)
                # if Frankfurter fails (404 etc.), use fallback
                if response.status_code != 200:
                    self.stdout.write(
                        self.style.WARNING(f"⚠️ Frankfurter failed ({response.status_code}) for {base} {date_str}, using fallback")
                    )
                    rates = self.fetch_from_fawaz(date_str, base, quote)
                else:
                    # Frankfurter OK
                    data = response.json()
                    rates = data.get("rates", {})

                    if not rates:
                        self.stdout.write(
                            self.style.WARNING(f"⚠️ Frankfurter: No rates for {base} on {date_str}, using fallback")
                        )
                        rates = self.fetch_from_fawaz(date_str, base, quote)
            except Exception as e:
                # fallback on exception too
                self.stdout.write(
                    self.style.WARNING(f"⚠️ Exception for {base} ({date_str}): {e}, using fallback")
                )
                rates = self.fetch_from_fawaz(date_str, base, quote)
                failed += 1
    
            rate = rates.get(base, None) or rates.get(base.lower(), None)
            if rate:
                if record.provider_rate is not None:
                    record.market_rate = min(rate, record.provider_rate)
                else:
                    record.market_rate = rate
                record.save(update_fields=["market_rate"])
                updated += 1
                self.stdout.write(
                    self.style.SUCCESS(f"✅ {date_str} | {base}->{quote} = {rate}")
                )
            else:
                failed += 1
                self.stdout.write(
                    self.style.WARNING(f"⚠️ Missing rate for {base}->{quote} on {date_str}")
                )

        self.stdout.write(
            self.style.SUCCESS(f"\n✅ Done! Updated {updated}/{total_records} records | Failed: {failed}\n")
        )

    # ---------------------------
    # 🔁 Fallback fetcher
    # ---------------------------
    def fetch_from_fawaz(self, date_str, base, quote):
        """Fetch rates from Fawaz Ahmed’s CDN as fallback."""
        base = base.lower()
        quote = quote.lower()
        url = self.FALLBACK_URL_TEMPLATE.format(date=date_str, apiVersion="v1", quote=quote)
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if quote in data :
                    return data[quote]
                else:
                    self.stdout.write(
                        self.style.WARNING(f"⚠️ No fallback rate found in data for {base}->{quote}")
                    )
                    return {}
            else:
                self.stdout.write(
                    self.style.WARNING(f"⚠️ Fallback failed {base}->{quote}: {response.status_code}")
                )
                print(url)
                return {}
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f"⚠️ Fallback error {base}->{quote}: {e}")
            )
            return {}
