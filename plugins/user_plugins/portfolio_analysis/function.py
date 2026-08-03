"""Long-only portfolio risk and return analysis using adjusted prices."""

from datetime import datetime, timezone
from math import isfinite, sqrt
import re
from typing import Any, Optional


_VALID_PERIODS = {"1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}
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


def _close_prices(data, symbols: list[str]):
    if data is None or data.empty:
        raise ValueError("No portfolio price history was returned")
    if getattr(data.columns, "nlevels", 1) > 1:
        level_zero = list(data.columns.get_level_values(0))
        level_one = list(data.columns.get_level_values(1))
        if "Close" in level_zero:
            close = data["Close"]
        elif "Close" in level_one:
            close = data.xs("Close", axis=1, level=1)
        else:
            raise ValueError("Downloaded market data did not include closing prices")
    else:
        if "Close" not in data.columns:
            raise ValueError("Downloaded market data did not include closing prices")
        close = data[["Close"]].rename(columns={"Close": symbols[0]})
    close.columns = [str(column).upper() for column in close.columns]
    return close


def _annualized_return(daily_returns, sessions: int = 252):
    if len(daily_returns) == 0:
        return None
    growth = float((1 + daily_returns).prod())
    return (growth ** (sessions / len(daily_returns))) - 1 if growth > 0 else -1.0


def _maximum_drawdown(daily_returns):
    wealth = (1 + daily_returns).cumprod()
    return float(((wealth / wealth.cummax()) - 1).min())


def portfolio_analysis(
    symbols: list[str],
    weights: Optional[list[float]] = None,
    period: str = "1y",
    benchmark: str = "SPY",
    risk_free_rate_percent: float = 0.0,
) -> dict:
    """Analyze a daily-rebalanced, long-only portfolio and optional benchmark."""
    import yfinance as yf

    if not isinstance(symbols, list) or not 1 <= len(symbols) <= 20:
        raise ValueError("symbols must contain between 1 and 20 entries")
    normalized_symbols = [_normalize_symbol(symbol) for symbol in symbols]
    if len(set(normalized_symbols)) != len(normalized_symbols):
        raise ValueError("symbols must not contain duplicates")
    period = str(period).strip().lower()
    if period not in _VALID_PERIODS:
        raise ValueError(f"Unsupported period: {period}")
    benchmark_symbol = _normalize_symbol(benchmark) if benchmark else None

    if weights is None:
        normalized_weights = [1 / len(normalized_symbols)] * len(normalized_symbols)
    else:
        if not isinstance(weights, list) or len(weights) != len(normalized_symbols):
            raise ValueError("weights must have the same number of entries as symbols")
        try:
            numeric_weights = [float(weight) for weight in weights]
        except (TypeError, ValueError) as exc:
            raise ValueError("weights must contain only numbers") from exc
        if any(not isfinite(weight) or weight < 0 for weight in numeric_weights):
            raise ValueError("weights must be finite, non-negative numbers")
        total_weight = sum(numeric_weights)
        if total_weight <= 0:
            raise ValueError("weights must sum to more than zero")
        normalized_weights = [weight / total_weight for weight in numeric_weights]

    download_symbols = list(normalized_symbols)
    if benchmark_symbol and benchmark_symbol not in download_symbols:
        download_symbols.append(benchmark_symbol)
    data = yf.download(
        tickers=download_symbols,
        period=period,
        interval="1d",
        auto_adjust=True,
        repair=True,
        progress=False,
        threads=True,
        group_by="column",
        timeout=10,
        multi_level_index=True,
    )
    close = _close_prices(data, download_symbols)
    missing = [symbol for symbol in download_symbols if symbol not in close.columns]
    if missing:
        raise ValueError("No closing prices were returned for: " + ", ".join(missing))

    asset_prices = close[normalized_symbols].dropna(how="any")
    asset_returns = asset_prices.pct_change(fill_method=None).dropna(how="any")
    if len(asset_returns) < 2:
        raise ValueError("At least three shared price observations are required")

    portfolio_returns = asset_returns.mul(normalized_weights, axis=1).sum(axis=1)
    annual_return = _annualized_return(portfolio_returns)
    annual_volatility = float(portfolio_returns.std(ddof=1) * sqrt(252))
    try:
        risk_free_rate = float(risk_free_rate_percent) / 100
    except (TypeError, ValueError) as exc:
        raise ValueError("risk_free_rate_percent must be a finite number") from exc
    if not isfinite(risk_free_rate):
        raise ValueError("risk_free_rate_percent must be a finite number")
    annualized_mean_return = float(portfolio_returns.mean() * 252)
    sharpe_ratio = (
        (annualized_mean_return - risk_free_rate) / annual_volatility
        if annual_volatility > 0 else None
    )

    per_asset = []
    for symbol, weight in zip(normalized_symbols, normalized_weights):
        returns = asset_returns[symbol]
        per_asset.append({
            "symbol": symbol,
            "weight_percent": round(weight * 100, 4),
            "total_return_percent": _round_number(((1 + returns).prod() - 1) * 100, 4),
            "annualized_volatility_percent": _round_number(returns.std(ddof=1) * sqrt(252) * 100, 4),
        })

    benchmark_result = None
    if benchmark_symbol:
        benchmark_prices = close[benchmark_symbol].reindex(asset_prices.index).dropna()
        benchmark_returns = benchmark_prices.pct_change(fill_method=None).dropna()
        aligned = portfolio_returns.to_frame("portfolio").join(
            benchmark_returns.rename("benchmark"), how="inner"
        ).dropna()
        if len(aligned) >= 2:
            benchmark_variance = float(aligned["benchmark"].var(ddof=1))
            beta = (
                float(aligned["portfolio"].cov(aligned["benchmark"])) / benchmark_variance
                if benchmark_variance > 0 else None
            )
            benchmark_annual_return = _annualized_return(aligned["benchmark"])
            benchmark_result = {
                "symbol": benchmark_symbol,
                "observations": int(len(aligned)),
                "annualized_return_percent": _round_number(
                    benchmark_annual_return * 100 if benchmark_annual_return is not None else None, 4
                ),
                "annualized_volatility_percent": _round_number(
                    aligned["benchmark"].std(ddof=1) * sqrt(252) * 100, 4
                ),
                "correlation": _round_number(aligned["portfolio"].corr(aligned["benchmark"]), 4),
                "beta": _round_number(beta, 4),
            }

    return {
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "period": period,
        "start_date": str(asset_returns.index[0]),
        "end_date": str(asset_returns.index[-1]),
        "observations": int(len(portfolio_returns)),
        "portfolio": {
            "total_return_percent": _round_number(((1 + portfolio_returns).prod() - 1) * 100, 4),
            "annualized_return_percent": _round_number(annual_return * 100 if annual_return is not None else None, 4),
            "annualized_volatility_percent": _round_number(annual_volatility * 100, 4),
            "sharpe_ratio": _round_number(sharpe_ratio, 4),
            "maximum_drawdown_percent": _round_number(_maximum_drawdown(portfolio_returns) * 100, 4),
            "best_day_percent": _round_number(portfolio_returns.max() * 100, 4),
            "worst_day_percent": _round_number(portfolio_returns.min() * 100, 4),
        },
        "assets": per_asset,
        "benchmark": benchmark_result,
        "methodology": "Adjusted closes; daily rebalancing; 252 sessions/year; weights normalized to 100%.",
        "source": "Yahoo Finance via yfinance",
    }
