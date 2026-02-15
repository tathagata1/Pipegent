import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional


API_ROOT = "https://api.github.com"
USER_AGENT = "PipegentGithubFetcher/1.0"


def _request(path: str, auth_token: Optional[str] = None, params: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    url = urllib.parse.urljoin(API_ROOT, path)
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
    }
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="replace")
        raise ConnectionError(f"GitHub API error {exc.code}: {error_text}") from exc
    except urllib.error.URLError as exc:
        reason = exc.reason if hasattr(exc, "reason") else str(exc)
        raise ConnectionError(f"GitHub API request failed: {reason}") from exc


def github_repo_fetcher(
    owner: str,
    repo: str,
    branch: Optional[str] = None,
    path: Optional[str] = None,
    auth_token: Optional[str] = None,
) -> Dict[str, Any]:
    if not owner or not repo:
        raise ValueError("owner and repo are required.")

    repo_path = f"/repos/{owner}/{repo}"
    repo_data = _request(repo_path, auth_token=auth_token)

    result: Dict[str, Any] = {
        "full_name": repo_data.get("full_name", ""),
        "description": repo_data.get("description"),
        "default_branch": repo_data.get("default_branch"),
        "stars": repo_data.get("stargazers_count"),
        "forks": repo_data.get("forks_count"),
        "open_issues": repo_data.get("open_issues_count"),
        "license": (repo_data.get("license") or {}).get("name"),
        "url": repo_data.get("html_url"),
    }

    if path:
        params = {"ref": branch or repo_data.get("default_branch", "main")}
        contents = _request(f"{repo_path}/contents/{path}", auth_token=auth_token, params=params)
        if contents.get("type") != "file":
            raise ValueError(f"Requested path '{path}' is not a file.")
        encoded = contents.get("content", "")
        decoded_bytes = base64.b64decode(encoded.encode("utf-8"))
        text = decoded_bytes.decode("utf-8", errors="replace")
        result["file"] = {
            "path": contents.get("path"),
            "size": contents.get("size"),
            "encoding": contents.get("encoding"),
            "download_url": contents.get("download_url"),
            "content": text,
        }

    return result
