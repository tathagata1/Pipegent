"""Symbol-focused finance news from Yahoo Finance."""

from datetime import datetime, timezone

from plugins.finance_common import get_yfinance, json_safe, normalize_symbol, utc_now


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
    return json_safe(value)


def finance_news(symbol: str, limit: int = 8, tab: str = "news") -> dict:
    """Return normalized recent headlines associated with a market symbol."""
    symbol = normalize_symbol(symbol)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 25:
        raise ValueError("limit must be an integer between 1 and 25")
    normalized_tab = str(tab).strip().lower()
    if normalized_tab not in {"news", "all", "press releases"}:
        raise ValueError("tab must be news, all, or press releases")

    raw_items = get_yfinance().Ticker(symbol).get_news(count=limit, tab=normalized_tab)
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
            "title": json_safe(content.get("title")),
            "publisher": json_safe(publisher),
            "published_at": _published_time(item, content),
            "summary": json_safe(content.get("summary") or content.get("description")),
            "url": json_safe(url),
            "thumbnail": json_safe(thumbnail),
            "type": json_safe(content.get("contentType") or item.get("type")),
        })

    return {
        "symbol": symbol,
        "fetched_at_utc": utc_now(),
        "tab": normalized_tab,
        "article_count": len(articles),
        "articles": articles[:limit],
        "source": "Yahoo Finance via yfinance",
    }
