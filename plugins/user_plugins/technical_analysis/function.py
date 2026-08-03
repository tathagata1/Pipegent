"""Deterministic technical indicators calculated from yfinance prices."""

from math import sqrt

from plugins.finance_common import history_frame, round_number, utc_now


def technical_analysis(
    symbol: str,
    period: str = "1y",
    interval: str = "1d",
    short_window: int = 20,
    long_window: int = 50,
    rsi_window: int = 14,
) -> dict:
    """Calculate trend, momentum, volatility, RSI, and drawdown statistics."""
    for name, value in (("short_window", short_window), ("long_window", long_window), ("rsi_window", rsi_window)):
        if not isinstance(value, int) or isinstance(value, bool) or value < 2:
            raise ValueError(f"{name} must be an integer of at least 2")
    if short_window >= long_window:
        raise ValueError("short_window must be smaller than long_window")

    symbol, frame = history_frame(symbol, period=period, interval=interval, auto_adjust=True)
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
    rsi_value = round_number(rsi.iloc[-1], 2)
    rsi_signal = "overbought" if rsi_value is not None and rsi_value >= 70 else (
        "oversold" if rsi_value is not None and rsi_value <= 30 else "neutral"
    )

    return {
        "symbol": symbol,
        "fetched_at_utc": utc_now(),
        "period": period,
        "interval": interval,
        "observations": int(len(close)),
        "last_date": str(close.index[-1]),
        "last_price": round_number(price),
        "trend": trend,
        "rsi_signal": rsi_signal,
        "indicators": {
            "sma_short": round_number(sma_short_value),
            "sma_long": round_number(sma_long_value),
            "ema_short": round_number(short_ema.iloc[-1]),
            "ema_long": round_number(long_ema.iloc[-1]),
            "rsi": rsi_value,
            "momentum_20_period_percent": round_number(momentum, 4),
            "annualized_volatility_percent": round_number(
                annualized_volatility * 100 if annualized_volatility is not None else None, 4
            ),
            "maximum_drawdown_percent": round_number(float(drawdown.min()) * 100, 4),
        },
        "windows": {"short": short_window, "long": long_window, "rsi": rsi_window},
        "methodology": "Adjusted closing prices; Wilder-style RSI; 252 sessions/year for daily volatility.",
        "source": "Yahoo Finance via yfinance",
    }
