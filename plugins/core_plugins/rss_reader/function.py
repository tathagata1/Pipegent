import datetime as dt
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional


DEFAULT_MAX_ITEMS = 10
MAX_LIMIT = 50
DEFAULT_TIMEOUT = 15.0


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _extract_text(node: Optional[ET.Element]) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.strip()


def _extract_entry(entry: ET.Element) -> Dict[str, Any]:
    children: Dict[str, List[ET.Element]] = {}
    for child in entry:
        children.setdefault(_local_name(child.tag), []).append(child)

    def first(tag: str) -> Optional[ET.Element]:
        values = children.get(tag)
        return values[0] if values else None

    title = _extract_text(first("title"))
    summary = _extract_text(first("description") or first("summary") or first("content"))

    link = ""
    if "link" in children:
        for candidate in children["link"]:
            href = candidate.attrib.get("href") or candidate.text or ""
            rel = candidate.attrib.get("rel", "alternate")
            if rel in {"alternate", "self"} and href:
                link = href.strip()
                break
        if not link and children["link"][0].text:
            link = children["link"][0].text.strip()

    if not link:
        guid = first("guid")
        if guid is not None:
            link = _extract_text(guid)

    published = (
        _extract_text(first("pubDate"))
        or _extract_text(first("published"))
        or _extract_text(first("updated"))
    )

    return {
        "title": title,
        "link": link,
        "summary": summary,
        "published": published,
    }


def rss_reader(
    url: str,
    max_items: Optional[int] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    if not url or not url.strip():
        raise ValueError("A feed URL is required.")
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Only HTTP(S) URLs are supported.")

    limit = DEFAULT_MAX_ITEMS if max_items is None else max(1, min(MAX_LIMIT, max_items))
    run_timeout = timeout if timeout and timeout > 0 else DEFAULT_TIMEOUT

    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "User-Agent": "PipegentRssReader/1.0",
            "Accept": "application/rss+xml, application/atom+xml, */*",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=run_timeout) as response:
            data = response.read()
    except urllib.error.URLError as exc:
        reason = exc.reason if hasattr(exc, "reason") else str(exc)
        raise ConnectionError(f"Failed to download feed: {reason}") from exc

    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"Feed parsing failed: {exc}") from exc

    channel = root.find("channel")
    if channel is None and _local_name(root.tag) == "rss":
        entries = root.findall(".//item")
        feed_title = _extract_text(root.find("./channel/title"))
    elif _local_name(root.tag).lower() == "feed":
        entries = root.findall(".//{*}entry")
        feed_title = _extract_text(root.find("./{*}title"))
    else:
        entries = root.findall(".//item")
        feed_title = _extract_text(root.find("./title"))

    parsed_entries = [_extract_entry(entry) for entry in entries[:limit]]

    return {
        "feed_title": feed_title or "",
        "entry_count": len(parsed_entries),
        "fetched_at": dt.datetime.utcnow().isoformat() + "Z",
        "entries": parsed_entries,
    }
