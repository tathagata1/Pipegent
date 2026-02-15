import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional


DEFAULT_TIMEOUT = 20.0
DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "User-Agent": "PipegentHttpPost/1.0",
}


def http_post_json(
    url: str,
    payload: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object (dictionary).")
    if not url or not url.strip():
        raise ValueError("A URL is required.")

    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Only HTTP(S) URLs are supported.")

    run_timeout = timeout if timeout and timeout > 0 else DEFAULT_TIMEOUT
    merged_headers = dict(DEFAULT_HEADERS)
    if headers:
        for key, value in headers.items():
            merged_headers[str(key)] = str(value)

    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=merged_headers, method="POST")

    try:
        with urllib.request.urlopen(request, timeout=run_timeout) as response:
            body = response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
            return {
                "status": response.status,
                "headers": dict(response.headers.items()),
                "body": body,
            }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(exc.headers.get_content_charset() or "utf-8", errors="replace")
        return {
            "status": exc.code,
            "headers": dict(exc.headers.items()) if exc.headers else {},
            "body": body,
        }
    except urllib.error.URLError as exc:
        reason = exc.reason if hasattr(exc, "reason") else str(exc)
        raise ConnectionError(f"POST request failed: {reason}") from exc
