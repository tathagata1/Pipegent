from pathlib import Path
from typing import Iterable, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
USER_FILES_DIR = PROJECT_ROOT / "user_files"


def ensure_user_files_dir() -> Path:
    USER_FILES_DIR.mkdir(parents=True, exist_ok=True)
    return USER_FILES_DIR


def _is_within_project(path: Path) -> bool:
    try:
        path.relative_to(PROJECT_ROOT)
        return True
    except ValueError:
        return False


def resolve_user_file(
    path_str: str,
    expected_extensions: Optional[Iterable[str]] = None,
) -> Path:
    """
    Resolve a user-provided file path. Users may reference absolute OS paths, but the actual
    files are stored under PROJECT_ROOT/user_files. This helper normalizes the path, searches
    user_files, ensures the target stays inside the repository, and enforces optional extensions.
    """

    ensure_user_files_dir()
    raw = Path(path_str).expanduser()
    candidates = []

    if raw.is_absolute():
        normalized = raw.resolve()
        if _is_within_project(normalized):
            candidates.append(normalized)
        else:
            candidates.append((USER_FILES_DIR / raw.name).resolve())
    else:
        candidates.append((PROJECT_ROOT / raw).resolve())
        candidates.append((USER_FILES_DIR / raw).resolve())

    if raw.name:
        candidates.append((USER_FILES_DIR / raw.name).resolve())

    seen = set()
    expected = tuple(e.lower() for e in expected_extensions) if expected_extensions else ()

    for candidate in candidates:
        if not _is_within_project(candidate):
            continue
        signature = str(candidate)
        if signature in seen:
            continue
        seen.add(signature)
        if not candidate.exists():
            continue
        if expected and candidate.suffix.lower() not in expected:
            continue
        return candidate

    raise FileNotFoundError(
        f"File '{path_str}' not found inside the workspace. "
        f"Place user-provided files under '{USER_FILES_DIR.relative_to(PROJECT_ROOT)}'."
    )
