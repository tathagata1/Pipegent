import sqlite3
from typing import Any, Dict, List, Optional

from services.path_utils import resolve_user_file

DEFAULT_MAX_ROWS = 50


def sqlite_query(
    db_path: str,
    query: str,
    parameters: Optional[List[Any]] = None,
    max_rows: Optional[int] = None,
) -> Dict[str, Any]:
    database = resolve_user_file(db_path)
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
