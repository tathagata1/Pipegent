"""Latest market snapshot from Yahoo Finance."""

from datetime import datetime, timezone
from math import isfinite
import re
from typing import Any, Optional


_FAST_INFO_FIELDS = (
    "currency", "exchange", "timezone", "quoteType", "lastPrice", "previousClose",
    "open", "dayHigh", "dayLow", "lastVolume", "marketCap", "yearHigh", "yearLow",
    "tenDayAverageVolume", "threeMonthAverageVolume",
)
_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9^=._-]{1,32}$")


def _normalize_symbol(symbol: str) -> str:
    if not isinstance(symbol, str):
        raise ValueError("symbol must be a string")
    normalized = symbol.strip().upper()
    if not _SYMBOL_PATTERN.fullmatch(normalized):
        raise ValueError(
            "symbol must be 1-32 characters and contain only letters, numbers, "
            "^, =, ., _, or -"
        )
    return normalized


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if isfinite(value) else None
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            pass
    return str(value)


def _round_number(value: Any, digits: int = 6) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, digits) if isfinite(number) else None


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
    import yfinance as yf

    symbol = _normalize_symbol(symbol)
    fast_info = yf.Ticker(symbol).fast_info
    values = {key: _json_safe(_read_fast_value(fast_info, key)) for key in _FAST_INFO_FIELDS}

    last_price = _round_number(values["lastPrice"])
    previous_close = _round_number(values["previousClose"])
    change = None
    change_percent = None
    if last_price is not None and previous_close not in (None, 0):
        change = round(last_price - previous_close, 6)
        change_percent = round((change / previous_close) * 100, 4)

    return {
        "symbol": symbol,
        "as_of_utc": datetime.now(timezone.utc).isoformat(),
        "currency": values["currency"],
        "exchange": values["exchange"],
        "timezone": values["timezone"],
        "quote_type": values["quoteType"],
        "last_price": last_price,
        "previous_close": previous_close,
        "change": change,
        "change_percent": change_percent,
        "open": _round_number(values["open"]),
        "day_high": _round_number(values["dayHigh"]),
        "day_low": _round_number(values["dayLow"]),
        "volume": _round_number(values["lastVolume"], 0),
        "market_cap": _round_number(values["marketCap"], 0),
        "year_high": _round_number(values["yearHigh"]),
        "year_low": _round_number(values["yearLow"]),
        "ten_day_average_volume": _round_number(values["tenDayAverageVolume"], 0),
        "three_month_average_volume": _round_number(values["threeMonthAverageVolume"], 0),
        "source": "Yahoo Finance via yfinance",
    }
