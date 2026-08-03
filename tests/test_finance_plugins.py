import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from plugins.user_plugins.company_fundamentals.function import company_fundamentals
from plugins.user_plugins.finance_news.function import finance_news
from plugins.user_plugins.market_quote.function import market_quote

try:
    import pandas as pd
except ImportError:  # The full requirements install supplies pandas through yfinance.
    pd = None

if pd is not None:
    from plugins.user_plugins.market_history.function import market_history
    from plugins.user_plugins.portfolio_analysis.function import portfolio_analysis
    from plugins.user_plugins.technical_analysis.function import technical_analysis


FINANCE_PLUGIN_NAMES = {
    "company_fundamentals",
    "finance_news",
    "market_history",
    "market_quote",
    "portfolio_analysis",
    "technical_analysis",
}


class FakeTicker:
    def __init__(self, symbol):
        self.symbol = symbol
        self.fast_info = {
            "currency": "USD",
            "exchange": "NMS",
            "timezone": "America/New_York",
            "quoteType": "EQUITY",
            "lastPrice": 105.0,
            "previousClose": 100.0,
            "open": 101.0,
            "dayHigh": 106.0,
            "dayLow": 99.5,
            "lastVolume": 1_500_000,
            "marketCap": 2_500_000_000,
            "yearHigh": 110.0,
            "yearLow": 70.0,
            "tenDayAverageVolume": 1_400_000,
            "threeMonthAverageVolume": 1_300_000,
        }

    def get_info(self):
        return {
            "longName": "Example Incorporated",
            "quoteType": "EQUITY",
            "sector": "Technology",
            "marketCap": 2_500_000_000,
            "trailingPE": 22.5,
            "profitMargins": 0.2,
            "totalRevenue": 1_000_000_000,
            "recommendationKey": "buy",
        }

    def get_news(self, count=8, tab="news"):
        return [{
            "content": {
                "title": "Example reports results",
                "provider": {"displayName": "Example Wire"},
                "pubDate": "2026-08-01T12:00:00Z",
                "summary": "A short summary.",
                "canonicalUrl": {"url": "https://example.com/story"},
                "contentType": "STORY",
            }
        }][:count]

    def history(self, **kwargs):
        if pd is None:
            raise AssertionError("pandas is required for this fake history")
        index = pd.date_range("2026-01-01", periods=90, freq="B", tz="UTC")
        close = pd.Series([100 + index_value * 0.25 for index_value in range(90)], index=index)
        return pd.DataFrame({
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": 1_000_000,
            "Dividends": 0.0,
            "Stock Splits": 0.0,
        }, index=index)


def fake_download(tickers, **kwargs):
    index = pd.date_range("2025-01-01", periods=90, freq="B", tz="UTC")
    values = {}
    for symbol_index, symbol in enumerate(tickers):
        values[("Close", symbol)] = [
            100 + symbol_index * 10 + row * (0.1 + symbol_index * 0.03)
            for row in range(90)
        ]
    frame = pd.DataFrame(values, index=index)
    frame.columns = pd.MultiIndex.from_tuples(frame.columns, names=["Price", "Ticker"])
    return frame


def fake_yfinance():
    return SimpleNamespace(Ticker=FakeTicker, download=fake_download)


class FinancePluginContractTests(unittest.TestCase):
    def test_all_manifests_have_matching_functions(self):
        root = Path(__file__).parents[1] / "plugins" / "user_plugins"
        for name in FINANCE_PLUGIN_NAMES:
            manifest = json.loads((root / name / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["name"], name)
            self.assertEqual(manifest["execution_function"], name)
            self.assertEqual(manifest["input_schema"]["type"], "object")
            self.assertTrue((root / name / "function.py").is_file())

    def test_quote_calculates_change(self):
        with patch.dict(sys.modules, {"yfinance": fake_yfinance()}):
            result = market_quote(" aapl ")
        self.assertEqual(result["symbol"], "AAPL")
        self.assertEqual(result["change"], 5.0)
        self.assertEqual(result["change_percent"], 5.0)

    def test_fundamentals_are_grouped(self):
        with patch.dict(sys.modules, {"yfinance": fake_yfinance()}):
            result = company_fundamentals("msft")
        self.assertEqual(result["company"]["sector"], "Technology")
        self.assertEqual(result["valuation"]["trailing_pe"], 22.5)
        self.assertEqual(result["analyst"]["recommendation"], "buy")

    def test_news_normalizes_nested_yfinance_shape(self):
        with patch.dict(sys.modules, {"yfinance": fake_yfinance()}):
            result = finance_news("nvda", limit=3)
        self.assertEqual(result["article_count"], 1)
        self.assertEqual(result["articles"][0]["publisher"], "Example Wire")
        self.assertEqual(result["articles"][0]["url"], "https://example.com/story")


@unittest.skipIf(pd is None, "pandas is installed with the yfinance runtime dependency")
class FinancePluginAnalyticsTests(unittest.TestCase):
    def test_history_is_bounded_and_json_safe(self):
        with patch.dict(sys.modules, {"yfinance": fake_yfinance()}):
            result = market_history("aapl", max_rows=10)
        self.assertEqual(result["total_rows"], 90)
        self.assertEqual(result["returned_rows"], 10)
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["prices"]), 10)

    def test_technical_analysis_returns_indicators(self):
        with patch.dict(sys.modules, {"yfinance": fake_yfinance()}):
            result = technical_analysis("aapl")
        self.assertEqual(result["trend"], "bullish")
        self.assertEqual(result["rsi_signal"], "overbought")
        self.assertIsNotNone(result["indicators"]["maximum_drawdown_percent"])

    def test_portfolio_weights_are_normalized(self):
        with patch.dict(sys.modules, {"yfinance": fake_yfinance()}):
            result = portfolio_analysis(
                ["aapl", "msft"], weights=[60, 40], benchmark="spy"
            )
        self.assertEqual([asset["weight_percent"] for asset in result["assets"]], [60.0, 40.0])
        self.assertEqual(result["benchmark"]["symbol"], "SPY")
        self.assertIsNotNone(result["portfolio"]["annualized_return_percent"])


if __name__ == "__main__":
    unittest.main()
