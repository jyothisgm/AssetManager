import requests
from datetime import date
from decimal import Decimal
from common.logging_config import logger

BASE_URL = "https://api.frankfurter.dev/v1"
FALLBACK_URL_TEMPLATE = (
    "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{date}/v1/currencies/{quote}.json"
)
MIN_DATE = date(1999, 1, 4)  # Frankfurter earliest date


def fetch_market_rate(base_code: str, quote_code: str, date_obj: date) -> Decimal | None:
    """
    Fetch the market exchange rate for a given date between base_code and quote_code.
    Uses Frankfurter.dev first, then falls back to Fawaz CDN if needed.

    Args:
        base_code (str): The currency code you want the rate in (e.g. 'USD').
        quote_code (str): The other currency code to compare with (e.g. 'INR').
        date_obj (date): The date to fetch the rate for.

    Returns:
        Decimal | None: The market exchange rate (base per quote), or None if unavailable.
    """
    if not base_code or not quote_code:
        logger.warning("[fetch_market_rate] Missing base or quote currency code.")
        return None

    date_str = date_obj.strftime("%Y-%m-%d")
    base = base_code.upper()
    quote = quote_code.upper()

    # Frankfurter API (primary)
    url = f"{BASE_URL}/{date_str}"
    params = {"from": quote, "to": base}

    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            rate = data.get("rates", {}).get(base)
            if rate:
                logger.debug(f"✅ [Frankfurter] {quote}->{base} on {date_str} = {rate}")
                return Decimal(str(rate))
            else:
                logger.warning(f"⚠️ [Frankfurter] No rate found for {quote}->{base} on {date_str}")
        else:
            logger.warning(f"⚠️ [Frankfurter] {response.status_code} for {quote}->{base} ({date_str})")
    except Exception as e:
        logger.warning(f"⚠️ [Frankfurter] Exception fetching {quote}->{base} ({date_str}): {e}")

    # Fallback: Fawaz CDN
    return _fetch_from_fawaz(date_str, base, quote)


def _fetch_from_fawaz(date_str: str, base: str, quote: str) -> Decimal | None:
    """Fallback fetch from Fawaz Ahmed’s CDN."""
    url = FALLBACK_URL_TEMPLATE.format(date=date_str, quote=quote.lower())

    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            logger.warning(f"⚠️ [Fallback] {response.status_code} for {quote}->{base} ({date_str})")
            return None

        data = response.json()
        quote_data = data.get(quote.lower())
        if not quote_data:
            logger.warning(f"⚠️ [Fallback] No data key for {quote}->{base} on {date_str}")
            return None

        rate = quote_data.get(base.lower())
        if rate:
            logger.debug(f"✅ [Fallback] {quote}->{base} on {date_str} = {rate}")
            return Decimal(str(rate))
        else:
            logger.warning(f"⚠️ [Fallback] Missing {base} key in {quote}->{base} data.")
            return None
    except Exception as e:
        logger.warning(f"⚠️ [Fallback] Exception fetching {quote}->{base} ({date_str}): {e}")
        return None
