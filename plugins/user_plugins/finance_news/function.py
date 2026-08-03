"""Symbol-focused finance news from Yahoo Finance."""

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


def _nested(mapping, *path):
    value = mapping
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _published_time(item: dict, content: dict):
    value = content.get("pubDate") or item.get("providerPublishTime")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    return _json_safe(value)


def finance_news(symbol: str, limit: int = 8, tab: str = "news") -> dict:
    """Return normalized recent headlines associated with a market symbol."""
    import yfinance as yf

    symbol = _normalize_symbol(symbol)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 25:
        raise ValueError("limit must be an integer between 1 and 25")
    normalized_tab = str(tab).strip().lower()
    if normalized_tab not in {"news", "all", "press releases"}:
        raise ValueError("tab must be news, all, or press releases")

    raw_items = yf.Ticker(symbol).get_news(count=limit, tab=normalized_tab)
    articles = []
    for item in raw_items or []:
        if not isinstance(item, dict):
            continue
        content = item.get("content") if isinstance(item.get("content"), dict) else item
        provider = content.get("provider")
        publisher = provider.get("displayName") if isinstance(provider, dict) else item.get("publisher")
        url = (
            _nested(content, "canonicalUrl", "url")
            or _nested(content, "clickThroughUrl", "url")
            or item.get("link")
        )
        thumbnail = _nested(content, "thumbnail", "originalUrl") or _nested(item, "thumbnail", "resolutions")
        articles.append({
            "title": _json_safe(content.get("title")),
            "publisher": _json_safe(publisher),
            "published_at": _published_time(item, content),
            "summary": _json_safe(content.get("summary") or content.get("description")),
            "url": _json_safe(url),
            "thumbnail": _json_safe(thumbnail),
            "type": _json_safe(content.get("contentType") or item.get("type")),
        })

    return {
        "symbol": symbol,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "tab": normalized_tab,
        "article_count": len(articles),
        "articles": articles[:limit],
        "source": "Yahoo Finance via yfinance",
    }
