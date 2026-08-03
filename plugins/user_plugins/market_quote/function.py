"""Latest market snapshot from Yahoo Finance."""

from plugins.finance_common import (
    get_yfinance,
    json_safe,
    normalize_symbol,
    round_number,
    utc_now,
)


_FAST_INFO_FIELDS = (
    "currency", "exchange", "timezone", "quoteType", "lastPrice", "previousClose",
    "open", "dayHigh", "dayLow", "lastVolume", "marketCap", "yearHigh", "yearLow",
    "tenDayAverageVolume", "threeMonthAverageVolume",
)


def _read_fast_value(fast_info, key):
    try:
        return fast_info[key]
    except (KeyError, TypeError, ValueError):
        try:
            return fast_info.get(key)
        except (AttributeError, KeyError, TypeError, ValueError):
            return None


def market_quote(symbol: str) -> dict:
    """Return the latest available quote and trading-range data for a symbol."""
    symbol = normalize_symbol(symbol)
    fast_info = get_yfinance().Ticker(symbol).fast_info
    values = {key: json_safe(_read_fast_value(fast_info, key)) for key in _FAST_INFO_FIELDS}

    last_price = round_number(values["lastPrice"])
    previous_close = round_number(values["previousClose"])
    change = None
    change_percent = None
    if last_price is not None and previous_close not in (None, 0):
        change = round(last_price - previous_close, 6)
        change_percent = round((change / previous_close) * 100, 4)

    return {
        "symbol": symbol,
        "as_of_utc": utc_now(),
        "currency": values["currency"],
        "exchange": values["exchange"],
        "timezone": values["timezone"],
        "quote_type": values["quoteType"],
        "last_price": last_price,
        "previous_close": previous_close,
        "change": change,
        "change_percent": change_percent,
        "open": round_number(values["open"]),
        "day_high": round_number(values["dayHigh"]),
        "day_low": round_number(values["dayLow"]),
        "volume": round_number(values["lastVolume"], 0),
        "market_cap": round_number(values["marketCap"], 0),
        "year_high": round_number(values["yearHigh"]),
        "year_low": round_number(values["yearLow"]),
        "ten_day_average_volume": round_number(values["tenDayAverageVolume"], 0),
        "three_month_average_volume": round_number(values["threeMonthAverageVolume"], 0),
        "source": "Yahoo Finance via yfinance",
    }
