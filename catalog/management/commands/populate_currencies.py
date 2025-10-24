from django.core.management.base import BaseCommand
from catalog.models import Currency
from common.logging_config import logger


class Command(BaseCommand):
    help = "Populate the Currency table with ISO 4217 fiat and major cryptocurrencies."

    BASE_CODE = "EUR"

    # ----------------------------
    # 💱 Fiat Currencies (ISO 4217)
    # ----------------------------
    FIAT_CURRENCIES = [
        ("AED", "United Arab Emirates Dirham", "د.إ", "United Arab Emirates"),
        ("AFN", "Afghan Afghani", "؋", "Afghanistan"),
        ("ALL", "Albanian Lek", "L", "Albania"),
        ("AMD", "Armenian Dram", "֏", "Armenia"),
        ("ANG", "Netherlands Antillean Guilder", "ƒ", "Curaçao/Sint Maarten"),
        ("AOA", "Angolan Kwanza", "Kz", "Angola"),
        ("ARS", "Argentine Peso", "$", "Argentina"),
        ("AUD", "Australian Dollar", "$", "Australia"),
        ("AWG", "Aruban Florin", "ƒ", "Aruba"),
        ("AZN", "Azerbaijani Manat", "₼", "Azerbaijan"),
        ("BAM", "Bosnia-Herzegovina Convertible Mark", "KM", "Bosnia and Herzegovina"),
        ("BBD", "Barbados Dollar", "$", "Barbados"),
        ("BDT", "Bangladeshi Taka", "৳", "Bangladesh"),
        ("BGN", "Bulgarian Lev", "лв", "Bulgaria"),
        ("BHD", "Bahraini Dinar", "ب.د", "Bahrain"),
        ("BIF", "Burundian Franc", "FBu", "Burundi"),
        ("BMD", "Bermudian Dollar", "$", "Bermuda"),
        ("BND", "Brunei Dollar", "$", "Brunei"),
        ("BOB", "Boliviano", "Bs.", "Bolivia"),
        ("BRL", "Brazilian Real", "R$", "Brazil"),
        ("BSD", "Bahamian Dollar", "$", "Bahamas"),
        ("BTN", "Bhutanese Ngultrum", "Nu.", "Bhutan"),
        ("BWP", "Botswana Pula", "P", "Botswana"),
        ("BYN", "Belarusian Ruble", "Br", "Belarus"),
        ("BZD", "Belize Dollar", "$", "Belize"),
        ("CAD", "Canadian Dollar", "$", "Canada"),
        ("CHF", "Swiss Franc", "CHF", "Switzerland"),
        ("CLP", "Chilean Peso", "$", "Chile"),
        ("CNY", "Chinese Yuan", "¥", "China"),
        ("COP", "Colombian Peso", "$", "Colombia"),
        ("CRC", "Costa Rican Colón", "₡", "Costa Rica"),
        ("CUP", "Cuban Peso", "$", "Cuba"),
        ("CZK", "Czech Koruna", "Kč", "Czech Republic"),
        ("DKK", "Danish Krone", "kr", "Denmark"),
        ("DOP", "Dominican Peso", "RD$", "Dominican Republic"),
        ("DZD", "Algerian Dinar", "دج", "Algeria"),
        ("EGP", "Egyptian Pound", "£", "Egypt"),
        ("ERN", "Eritrean Nakfa", "Nfk", "Eritrea"),
        ("ETB", "Ethiopian Birr", "Br", "Ethiopia"),
        ("EUR", "Euro", "€", "European Union"),
        ("FJD", "Fiji Dollar", "$", "Fiji"),
        ("GBP", "Pound Sterling", "£", "United Kingdom"),
        ("GEL", "Georgian Lari", "₾", "Georgia"),
        ("GHS", "Ghanaian Cedi", "₵", "Ghana"),
        ("GIP", "Gibraltar Pound", "£", "Gibraltar"),
        ("GNF", "Guinean Franc", "FG", "Guinea"),
        ("GTQ", "Guatemalan Quetzal", "Q", "Guatemala"),
        ("GYD", "Guyana Dollar", "$", "Guyana"),
        ("HKD", "Hong Kong Dollar", "$", "Hong Kong"),
        ("HNL", "Honduran Lempira", "L", "Honduras"),
        ("HRK", "Croatian Kuna", "kn", "Croatia"),
        ("HUF", "Hungarian Forint", "Ft", "Hungary"),
        ("IDR", "Indonesian Rupiah", "Rp", "Indonesia"),
        ("ILS", "Israeli New Shekel", "₪", "Israel"),
        ("INR", "Indian Rupee", "₹", "India"),
        ("JPY", "Japanese Yen", "¥", "Japan"),
        ("KES", "Kenyan Shilling", "KSh", "Kenya"),
        ("KRW", "South Korean Won", "₩", "South Korea"),
        ("LKR", "Sri Lankan Rupee", "Rs", "Sri Lanka"),
        ("MAD", "Moroccan Dirham", "د.م.", "Morocco"),
        ("MXN", "Mexican Peso", "$", "Mexico"),
        ("MYR", "Malaysian Ringgit", "RM", "Malaysia"),
        ("NOK", "Norwegian Krone", "kr", "Norway"),
        ("NZD", "New Zealand Dollar", "$", "New Zealand"),
        ("PKR", "Pakistani Rupee", "₨", "Pakistan"),
        ("QAR", "Qatari Riyal", "﷼", "Qatar"),
        ("RUB", "Russian Ruble", "₽", "Russia"),
        ("SAR", "Saudi Riyal", "﷼", "Saudi Arabia"),
        ("SGD", "Singapore Dollar", "$", "Singapore"),
        ("THB", "Thai Baht", "฿", "Thailand"),
        ("USD", "US Dollar", "$", "United States"),
        ("ZAR", "South African Rand", "R", "South Africa"),
    ]

    # ----------------------------
    # ₿ Major Cryptocurrencies
    # ----------------------------
    CRYPTO_CURRENCIES = [
        ("BTC", "Bitcoin", "₿", "crypto", "Global"),
        ("ETH", "Ethereum", "Ξ", "crypto", "Global"),
        ("BNB", "Binance Coin", "BNB", "crypto", "Global"),
        ("SOL", "Solana", "◎", "crypto", "Global"),
        ("XRP", "Ripple", "XRP", "crypto", "Global"),
        ("ADA", "Cardano", "₳", "crypto", "Global"),
        ("DOGE", "Dogecoin", "Ð", "crypto", "Global"),
        ("DOT", "Polkadot", "DOT", "crypto", "Global"),
        ("MATIC", "Polygon", "MATIC", "crypto", "Global"),
        ("LTC", "Litecoin", "Ł", "crypto", "Global"),
        ("USDT", "Tether", "$", "crypto", "Global"),
        ("USDC", "USD Coin", "$", "crypto", "Global"),
        ("DAI", "Dai", "◈", "crypto", "Global"),
    ]

    def handle(self, *args, **options):
        logger.info("🚀 [populate_currencies] Starting currency population...")

        created_count = 0

        try:
            # --- Fiat Currencies ---
            for code, name, symbol, country in self.FIAT_CURRENCIES:
                Currency.objects.update_or_create(
                    code=code,
                    defaults={
                        "name": name,
                        "symbol": symbol,
                        "type": "fiat",
                        "country": country,
                        "is_base_currency": (code == self.BASE_CODE),
                        "rate_to_base": 1 if code == self.BASE_CODE else 0,
                    },
                )
                created_count += 1

            # --- Crypto Currencies ---
            for code, name, symbol, ctype, country in self.CRYPTO_CURRENCIES:
                Currency.objects.update_or_create(
                    code=code,
                    defaults={
                        "name": name,
                        "symbol": symbol,
                        "type": ctype,
                        "country": country,
                        "is_base_currency": False,
                        "rate_to_base": 0,
                    },
                )
                created_count += 1

            logger.info(f"✅ [populate_currencies] Seeded {created_count} currencies successfully.")
            logger.info(f"💶 [populate_currencies] Base currency set to {self.BASE_CODE}.")

        except Exception as e:
            logger.exception("🔥 [populate_currencies] Failed during currency population:")
            raise e

        logger.info("🎯 [populate_currencies] Completed successfully.")
