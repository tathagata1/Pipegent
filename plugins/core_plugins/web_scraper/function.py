import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Union


DEFAULT_TIMEOUT = 20.0
DEFAULT_MAX_BYTES = 200_000
DEFAULT_USER_AGENT = "PipegentWebScraper/1.0"


def web_scraper(
    url: str,
    timeout: Optional[Union[int, float]] = None,
    max_bytes: Optional[int] = None,
    user_agent: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Fetch the provided URL and return a subset of the response details.
    Response always includes HTTP status, content type, encoding, truncation flag, and the body snippet.
    """

    if not url or not url.strip():
        raise ValueError("A URL is required.")

    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Only absolute HTTP(S) URLs are supported.")

    run_timeout = float(timeout) if timeout is not None else DEFAULT_TIMEOUT
    if run_timeout <= 0:
        raise ValueError("timeout must be greater than zero.")

    byte_limit = int(max_bytes) if max_bytes is not None else DEFAULT_MAX_BYTES
    if byte_limit <= 0:
        raise ValueError("max_bytes must be greater than zero.")

    headers = {
        "User-Agent": user_agent.strip() if user_agent else DEFAULT_USER_AGENT,
        "Accept": "*/*",
    }
    request = urllib.request.Request(url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(request, timeout=run_timeout) as response:
            body_bytes = response.read(byte_limit + 1)  # +1 so we can flag truncation.
            truncated = len(body_bytes) > byte_limit
            content_bytes = body_bytes[:byte_limit]
            charset = response.headers.get_content_charset() or "utf-8"
            text = content_bytes.decode(charset, errors="replace")
            return {
                "status": response.status,
                "content_type": response.headers.get("Content-Type", ""),
                "encoding_used": charset,
                "truncated": truncated,
                "body": text,
            }
    except urllib.error.HTTPError as exc:
        error_body = exc.read(byte_limit if byte_limit > 0 else DEFAULT_MAX_BYTES)
        charset = "utf-8"
        content_type = ""
        if exc.headers:
            header_charset = exc.headers.get_content_charset()
            if header_charset:
                charset = header_charset
            content_type = exc.headers.get("Content-Type", "")
        return {
            "status": exc.code,
            "content_type": content_type,
            "encoding_used": charset,
            "truncated": False,
            "body": error_body.decode(charset, errors="replace"),
        }
    except urllib.error.URLError as exc:
        reason = exc.reason if hasattr(exc, "reason") else str(exc)
        raise ConnectionError(f"Failed to fetch {url}: {reason}") from exc
