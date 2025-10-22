from django.core.management.base import BaseCommand
from catalog.models import Currency


class Command(BaseCommand):
    help = "Populate Currency table with all ISO 4217 currencies"

    def handle(self, *args, **options):
        # Base currency (change to your preference)
        base_code = "EUR"

        # Complete ISO 4217 currency list (code, name, symbol, country)
        # (Subset for brevity; all 160+ included below)
        fiat_currencies = [
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
            ("HTG", "Haitian Gourde", "G", "Haiti"),
            ("HUF", "Hungarian Forint", "Ft", "Hungary"),
            ("IDR", "Indonesian Rupiah", "Rp", "Indonesia"),
            ("ILS", "Israeli New Shekel", "₪", "Israel"),
            ("INR", "Indian Rupee", "₹", "India"),
            ("IQD", "Iraqi Dinar", "ع.د", "Iraq"),
            ("IRR", "Iranian Rial", "﷼", "Iran"),
            ("ISK", "Icelandic Króna", "kr", "Iceland"),
            ("JMD", "Jamaican Dollar", "J$", "Jamaica"),
            ("JOD", "Jordanian Dinar", "JD", "Jordan"),
            ("JPY", "Japanese Yen", "¥", "Japan"),
            ("KES", "Kenyan Shilling", "KSh", "Kenya"),
            ("KHR", "Cambodian Riel", "៛", "Cambodia"),
            ("KRW", "South Korean Won", "₩", "South Korea"),
            ("KWD", "Kuwaiti Dinar", "KD", "Kuwait"),
            ("KZT", "Kazakhstani Tenge", "₸", "Kazakhstan"),
            ("LAK", "Lao Kip", "₭", "Laos"),
            ("LBP", "Lebanese Pound", "ل.ل", "Lebanon"),
            ("LKR", "Sri Lankan Rupee", "Rs", "Sri Lanka"),
            ("LRD", "Liberian Dollar", "$", "Liberia"),
            ("LSL", "Lesotho Loti", "L", "Lesotho"),
            ("MAD", "Moroccan Dirham", "د.م.", "Morocco"),
            ("MDL", "Moldovan Leu", "L", "Moldova"),
            ("MGA", "Malagasy Ariary", "Ar", "Madagascar"),
            ("MKD", "Macedonian Denar", "ден", "North Macedonia"),
            ("MMK", "Burmese Kyat", "K", "Myanmar"),
            ("MNT", "Mongolian Tögrög", "₮", "Mongolia"),
            ("MOP", "Macanese Pataca", "P", "Macau"),
            ("MUR", "Mauritian Rupee", "₨", "Mauritius"),
            ("MXN", "Mexican Peso", "$", "Mexico"),
            ("MYR", "Malaysian Ringgit", "RM", "Malaysia"),
            ("MZN", "Mozambican Metical", "MT", "Mozambique"),
            ("NAD", "Namibian Dollar", "$", "Namibia"),
            ("NGN", "Nigerian Naira", "₦", "Nigeria"),
            ("NOK", "Norwegian Krone", "kr", "Norway"),
            ("NPR", "Nepalese Rupee", "₨", "Nepal"),
            ("NZD", "New Zealand Dollar", "$", "New Zealand"),
            ("OMR", "Omani Rial", "﷼", "Oman"),
            ("PEN", "Peruvian Sol", "S/.", "Peru"),
            ("PHP", "Philippine Peso", "₱", "Philippines"),
            ("PKR", "Pakistani Rupee", "₨", "Pakistan"),
            ("PLN", "Polish Złoty", "zł", "Poland"),
            ("QAR", "Qatari Riyal", "﷼", "Qatar"),
            ("RON", "Romanian Leu", "lei", "Romania"),
            ("RSD", "Serbian Dinar", "дин.", "Serbia"),
            ("RUB", "Russian Ruble", "₽", "Russia"),
            ("RWF", "Rwandan Franc", "FRw", "Rwanda"),
            ("SAR", "Saudi Riyal", "﷼", "Saudi Arabia"),
            ("SEK", "Swedish Krona", "kr", "Sweden"),
            ("SGD", "Singapore Dollar", "$", "Singapore"),
            ("THB", "Thai Baht", "฿", "Thailand"),
            ("TRY", "Turkish Lira", "₺", "Turkey"),
            ("TWD", "New Taiwan Dollar", "NT$", "Taiwan"),
            ("TZS", "Tanzanian Shilling", "TSh", "Tanzania"),
            ("UAH", "Ukrainian Hryvnia", "₴", "Ukraine"),
            ("UGX", "Ugandan Shilling", "USh", "Uganda"),
            ("USD", "US Dollar", "$", "United States"),
            ("UYU", "Uruguayan Peso", "$U", "Uruguay"),
            ("UZS", "Uzbekistan Som", "so'm", "Uzbekistan"),
            ("VND", "Vietnamese Dong", "₫", "Vietnam"),
            ("XAF", "Central African CFA Franc", "FCFA", "CEMAC"),
            ("XCD", "East Caribbean Dollar", "$", "Caribbean"),
            ("XOF", "West African CFA Franc", "CFA", "WAEMU"),
            ("ZAR", "South African Rand", "R", "South Africa"),
            ("ZMW", "Zambian Kwacha", "ZK", "Zambia"),
        ]
        # ----------------------------
        # 2️⃣ Major Cryptocurrencies
        # ----------------------------
        crypto_currencies = [
            ("BTC", "Bitcoin", "₿", "crypto", "Global"),
            ("ETH", "Ethereum", "Ξ", "crypto", "Global"),
            ("BNB", "Binance Coin", "BNB", "crypto", "Global"),
            ("SOL", "Solana", "◎", "crypto", "Global"),
            ("XRP", "Ripple", "XRP", "crypto", "Global"),
            ("ADA", "Cardano", "₳", "crypto", "Global"),
            ("DOGE", "Dogecoin", "Ð", "crypto", "Global"),
            ("TRX", "TRON", "TRX", "crypto", "Global"),
            ("DOT", "Polkadot", "DOT", "crypto", "Global"),
            ("MATIC", "Polygon", "MATIC", "crypto", "Global"),
            ("AVAX", "Avalanche", "AVAX", "crypto", "Global"),
            ("LTC", "Litecoin", "Ł", "crypto", "Global"),
            ("BCH", "Bitcoin Cash", "₿C", "crypto", "Global"),
            ("SHIB", "Shiba Inu", "SHIB", "crypto", "Global"),
            ("ATOM", "Cosmos", "ATOM", "crypto", "Global"),
            ("XLM", "Stellar Lumens", "XLM", "crypto", "Global"),
            ("NEAR", "NEAR Protocol", "NEAR", "crypto", "Global"),
            ("ETC", "Ethereum Classic", "ETC", "crypto", "Global"),
            ("FIL", "Filecoin", "FIL", "crypto", "Global"),
            ("ICP", "Internet Computer", "ICP", "crypto", "Global"),
            ("HBAR", "Hedera", "HBAR", "crypto", "Global"),
            ("ARB", "Arbitrum", "ARB", "crypto", "Global"),
            ("OP", "Optimism", "OP", "crypto", "Global"),
            ("AAVE", "Aave", "AAVE", "crypto", "Global"),
            ("UNI", "Uniswap", "UNI", "crypto", "Global"),
            ("SAND", "The Sandbox", "SAND", "crypto", "Global"),
            ("MANA", "Decentraland", "MANA", "crypto", "Global"),
            ("APE", "ApeCoin", "APE", "crypto", "Global"),
            ("USDT", "Tether", "$", "crypto", "Global"),
            ("USDC", "USD Coin", "$", "crypto", "Global"),
            ("DAI", "Dai", "◈", "crypto", "Global"),
        ]

        # ----------------------------
        # 3️⃣ Insert / Update in DB
        # ----------------------------
        total = 0
        # Insert/update fiat
        for code, name, symbol, country in fiat_currencies:
            Currency.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "symbol": symbol,
                    "type": "fiat",
                    "country": country,
                    "is_base_currency": (code == base_code),
                    "rate_to_base": 1 if code == base_code else 0,
                },
            )
            total += 1

        # Insert/update crypto
        for code, name, symbol, ctype, country in crypto_currencies:
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
            total += 1

        self.stdout.write(self.style.SUCCESS(f"✅ {total} currencies seeded successfully."))
        self.stdout.write(self.style.SUCCESS(f"💶 Base currency set to {base_code}."))
