"""Curated company fundamentals from Yahoo Finance."""

from datetime import date, datetime, timezone
from math import isfinite
import re
from typing import Any


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
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            pass
    return str(value)


def _section(info: dict, fields: dict[str, str]) -> dict:
    return {output: _json_safe(info.get(source)) for output, source in fields.items()}


def company_fundamentals(symbol: str) -> dict:
    """Return a curated, stable subset of company profile and fundamental fields."""
    import yfinance as yf

    symbol = _normalize_symbol(symbol)
    info = yf.Ticker(symbol).get_info()
    if not isinstance(info, dict) or not info:
        raise ValueError(f"No company fundamentals were returned for {symbol}")

    return {
        "symbol": symbol,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "company": _section(info, {
            "name": "longName", "short_name": "shortName", "quote_type": "quoteType",
            "sector": "sector", "industry": "industry", "country": "country",
            "website": "website", "employees": "fullTimeEmployees",
            "business_summary": "longBusinessSummary",
        }),
        "market": _section(info, {
            "currency": "currency", "exchange": "exchange", "market_cap": "marketCap",
            "enterprise_value": "enterpriseValue", "shares_outstanding": "sharesOutstanding",
            "float_shares": "floatShares", "beta": "beta",
        }),
        "valuation": _section(info, {
            "trailing_pe": "trailingPE", "forward_pe": "forwardPE", "price_to_book": "priceToBook",
            "price_to_sales_ttm": "priceToSalesTrailing12Months",
            "enterprise_to_revenue": "enterpriseToRevenue", "enterprise_to_ebitda": "enterpriseToEbitda",
        }),
        "profitability": _section(info, {
            "profit_margin": "profitMargins", "operating_margin": "operatingMargins",
            "gross_margin": "grossMargins", "ebitda_margin": "ebitdaMargins",
            "return_on_assets": "returnOnAssets", "return_on_equity": "returnOnEquity",
        }),
        "growth": _section(info, {
            "revenue_growth": "revenueGrowth", "earnings_growth": "earningsGrowth",
            "earnings_quarterly_growth": "earningsQuarterlyGrowth",
        }),
        "financial_health": _section(info, {
            "total_revenue": "totalRevenue", "ebitda": "ebitda", "net_income": "netIncomeToCommon",
            "total_cash": "totalCash", "total_debt": "totalDebt", "free_cash_flow": "freeCashflow",
            "operating_cash_flow": "operatingCashflow", "debt_to_equity": "debtToEquity",
            "current_ratio": "currentRatio", "quick_ratio": "quickRatio",
        }),
        "dividends": _section(info, {
            "dividend_rate": "dividendRate", "dividend_yield": "dividendYield",
            "payout_ratio": "payoutRatio", "five_year_average_yield": "fiveYearAvgDividendYield",
            "ex_dividend_date": "exDividendDate",
        }),
        "analyst": _section(info, {
            "recommendation": "recommendationKey", "recommendation_mean": "recommendationMean",
            "analyst_count": "numberOfAnalystOpinions", "target_low": "targetLowPrice",
            "target_mean": "targetMeanPrice", "target_median": "targetMedianPrice",
            "target_high": "targetHighPrice",
        }),
        "source": "Yahoo Finance via yfinance",
    }
