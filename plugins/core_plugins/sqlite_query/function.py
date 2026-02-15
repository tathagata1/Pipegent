import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MAX_ROWS = 50


def _resolve_db(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    else:
        path = path.resolve()
    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"Database path '{path}' is outside the project root.") from exc
    return path


def sqlite_query(
    db_path: str,
    query: str,
    parameters: Optional[List[Any]] = None,
    max_rows: Optional[int] = None,
) -> Dict[str, Any]:
    database = _resolve_db(db_path)
    if not database.exists():
        raise FileNotFoundError(f"Database file not found: {database}")

    limit = DEFAULT_MAX_ROWS if max_rows is None else max(1, max_rows)

    params = tuple(parameters or [])

    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query, params)
        if query.strip().lower().startswith("select"):
            rows = cursor.fetchmany(limit)
            data = [dict(row) for row in rows]
            return {"row_count": len(data), "rows": data}
        else:
            conn.commit()
            return {"changes": cursor.rowcount}
