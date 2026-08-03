"""Deterministic technical indicators calculated from yfinance prices."""

from datetime import datetime, timezone
from math import isfinite, sqrt
import re
from typing import Any, Optional


_VALID_PERIODS = {"1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}
_VALID_INTERVALS = {"1d", "5d", "1wk", "1mo", "3mo"}
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


def _round_number(value: Any, digits: int = 6) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, digits) if isfinite(number) else None


def technical_analysis(
    symbol: str,
    period: str = "1y",
    interval: str = "1d",
    short_window: int = 20,
    long_window: int = 50,
    rsi_window: int = 14,
) -> dict:
    """Calculate trend, momentum, volatility, RSI, and drawdown statistics."""
    import yfinance as yf

    for name, value in (("short_window", short_window), ("long_window", long_window), ("rsi_window", rsi_window)):
        if not isinstance(value, int) or isinstance(value, bool) or value < 2:
            raise ValueError(f"{name} must be an integer of at least 2")
    if short_window >= long_window:
        raise ValueError("short_window must be smaller than long_window")

    symbol = _normalize_symbol(symbol)
    period = str(period).strip().lower()
    interval = str(interval).strip().lower()
    if period not in _VALID_PERIODS:
        raise ValueError(f"Unsupported period: {period}")
    if interval not in _VALID_INTERVALS:
        raise ValueError(f"Unsupported interval: {interval}")

    frame = yf.Ticker(symbol).history(
        period=period,
        interval=interval,
        auto_adjust=True,
        actions=False,
        repair=True,
        timeout=10,
        raise_errors=True,
    )
    if frame is None or frame.empty:
        raise ValueError(f"No price history was returned for {symbol}")
    close = frame["Close"].dropna().astype(float)
    minimum_rows = max(long_window, rsi_window + 1)
    if len(close) < minimum_rows:
        raise ValueError(f"At least {minimum_rows} price observations are required")

    short_sma = close.rolling(short_window).mean()
    long_sma = close.rolling(long_window).mean()
    short_ema = close.ewm(span=short_window, adjust=False).mean()
    long_ema = close.ewm(span=long_window, adjust=False).mean()

    delta = close.diff()
    average_gain = delta.clip(lower=0).ewm(alpha=1 / rsi_window, adjust=False, min_periods=rsi_window).mean()
    average_loss = (-delta.clip(upper=0)).ewm(alpha=1 / rsi_window, adjust=False, min_periods=rsi_window).mean()
    relative_strength = average_gain / average_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + relative_strength))
    if average_loss.iloc[-1] == 0:
        rsi.iloc[-1] = 100.0 if average_gain.iloc[-1] > 0 else 50.0

    returns = close.pct_change(fill_method=None).dropna()
    annualization = 252 if interval == "1d" else None
    annualized_volatility = returns.std(ddof=1) * sqrt(annualization) if annualization else None
    running_peak = close.cummax()
    drawdown = (close / running_peak) - 1
    price = float(close.iloc[-1])
    sma_short_value = float(short_sma.iloc[-1])
    sma_long_value = float(long_sma.iloc[-1])

    if price > sma_short_value > sma_long_value:
        trend = "bullish"
    elif price < sma_short_value < sma_long_value:
        trend = "bearish"
    else:
        trend = "mixed"

    lookback = min(20, len(close) - 1)
    momentum = ((price / float(close.iloc[-lookback - 1])) - 1) * 100
    rsi_value = _round_number(rsi.iloc[-1], 2)
    rsi_signal = "overbought" if rsi_value is not None and rsi_value >= 70 else (
        "oversold" if rsi_value is not None and rsi_value <= 30 else "neutral"
    )

    return {
        "symbol": symbol,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "period": period,
        "interval": interval,
        "observations": int(len(close)),
        "last_date": str(close.index[-1]),
        "last_price": _round_number(price),
        "trend": trend,
        "rsi_signal": rsi_signal,
        "indicators": {
            "sma_short": _round_number(sma_short_value),
            "sma_long": _round_number(sma_long_value),
            "ema_short": _round_number(short_ema.iloc[-1]),
            "ema_long": _round_number(long_ema.iloc[-1]),
            "rsi": rsi_value,
            "momentum_20_period_percent": _round_number(momentum, 4),
            "annualized_volatility_percent": _round_number(
                annualized_volatility * 100 if annualized_volatility is not None else None, 4
            ),
            "maximum_drawdown_percent": _round_number(float(drawdown.min()) * 100, 4),
        },
        "windows": {"short": short_window, "long": long_window, "rsi": rsi_window},
        "methodology": "Adjusted closing prices; Wilder-style RSI; 252 sessions/year for daily volatility.",
        "source": "Yahoo Finance via yfinance",
    }
