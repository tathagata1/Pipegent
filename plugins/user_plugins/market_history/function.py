"""Historical OHLCV market data from Yahoo Finance."""

from datetime import date, datetime, timezone
from math import isfinite
import re
from typing import Any, Dict, Optional


_VALID_PERIODS = {
    "1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"
}
_VALID_INTERVALS = {
    "1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"
}
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


def _validate_iso_date(value: Optional[str], name: str) -> Optional[str]:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise ValueError(f"{name} must use YYYY-MM-DD format") from exc


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if isfinite(value) else None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "to_pydatetime"):
        try:
            return value.to_pydatetime().isoformat()
        except (TypeError, ValueError):
            pass
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


def _frame_records(frame, max_rows: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, row in frame.tail(max_rows).iterrows():
        item: dict[str, Any] = {"date": _json_safe(index)}
        for column, value in row.items():
            key = re.sub(r"[^a-z0-9]+", "_", str(column).strip().lower()).strip("_")
            item[key] = _json_safe(value)
        records.append(item)
    return records


def market_history(
    symbol: str,
    period: str = "1y",
    interval: str = "1d",
    start: Optional[str] = None,
    end: Optional[str] = None,
    adjusted: bool = True,
    include_actions: bool = False,
    max_rows: int = 260,
) -> dict:
    """Return bounded OHLCV history plus a compact performance summary."""
    import yfinance as yf

    if not isinstance(max_rows, int) or isinstance(max_rows, bool) or not 1 <= max_rows <= 1000:
        raise ValueError("max_rows must be an integer between 1 and 1000")

    symbol = _normalize_symbol(symbol)
    period = str(period).strip().lower()
    interval = str(interval).strip().lower()
    if period not in _VALID_PERIODS:
        raise ValueError(f"Unsupported period: {period}")
    if interval not in _VALID_INTERVALS:
        raise ValueError(f"Unsupported interval: {interval}")
    start = _validate_iso_date(start, "start")
    end = _validate_iso_date(end, "end")
    if start and end and start >= end:
        raise ValueError("start must be earlier than end")

    history_options: Dict[str, Any] = {
        "interval": interval,
        "auto_adjust": bool(adjusted),
        "actions": bool(include_actions),
        "repair": True,
        "timeout": 10,
        "raise_errors": True,
    }
    if start or end:
        history_options.update({"start": start, "end": end})
    else:
        history_options["period"] = period

    frame = yf.Ticker(symbol).history(**history_options)
    if frame is None or frame.empty:
        raise ValueError(f"No price history was returned for {symbol}")
    close = frame["Close"].dropna()
    first_close = _round_number(close.iloc[0]) if not close.empty else None
    last_close = _round_number(close.iloc[-1]) if not close.empty else None
    total_return = None
    if first_close not in (None, 0) and last_close is not None:
        total_return = round(((last_close / first_close) - 1) * 100, 4)

    return {
        "symbol": symbol,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "period": period,
        "interval": interval,
        "start": start,
        "end": end,
        "adjusted": bool(adjusted),
        "include_actions": bool(include_actions),
        "total_rows": int(len(frame)),
        "returned_rows": min(int(len(frame)), max_rows),
        "truncated": len(frame) > max_rows,
        "summary": {
            "first_date": str(frame.index[0]),
            "last_date": str(frame.index[-1]),
            "first_close": first_close,
            "last_close": last_close,
            "total_return_percent": total_return,
        },
        "prices": _frame_records(frame, max_rows),
        "source": "Yahoo Finance via yfinance",
    }
