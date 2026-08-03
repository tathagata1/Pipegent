"""Historical OHLCV market data from Yahoo Finance."""

from typing import Optional

from plugins.finance_common import (
    frame_records,
    history_frame,
    round_number,
    utc_now,
)


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
    if not isinstance(max_rows, int) or isinstance(max_rows, bool) or not 1 <= max_rows <= 1000:
        raise ValueError("max_rows must be an integer between 1 and 1000")

    symbol, frame = history_frame(
        symbol,
        period=period,
        interval=interval,
        start=start,
        end=end,
        auto_adjust=adjusted,
        actions=include_actions,
    )
    close = frame["Close"].dropna()
    first_close = round_number(close.iloc[0]) if not close.empty else None
    last_close = round_number(close.iloc[-1]) if not close.empty else None
    total_return = None
    if first_close not in (None, 0) and last_close is not None:
        total_return = round(((last_close / first_close) - 1) * 100, 4)

    return {
        "symbol": symbol,
        "fetched_at_utc": utc_now(),
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
        "prices": frame_records(frame, max_rows),
        "source": "Yahoo Finance via yfinance",
    }
