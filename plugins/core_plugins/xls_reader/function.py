from pathlib import Path
from typing import Any, Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LIMIT = 200


def _resolve(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    else:
        path = path.resolve()
    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"File '{path}' is outside the project root.") from exc
    if path.suffix.lower() != ".xls":
        raise ValueError("xls_reader only handles .xls files.")
    if not path.exists():
        raise FileNotFoundError(f"XLS file not found: {path}")
    return path


def xls_reader(
    file_path: str,
    sheet_name: Optional[str] = None,
    max_rows: Optional[int] = None,
    has_header: bool = True,
) -> Dict[str, Any]:
    try:
        import xlrd  # type: ignore
    except ImportError as exc:
        raise ImportError("xls_reader requires the 'xlrd' package.") from exc

    path = _resolve(file_path)
    workbook = xlrd.open_workbook(path)
    worksheet = workbook.sheet_by_name(sheet_name) if sheet_name else workbook.sheet_by_index(0)

    limit = DEFAULT_LIMIT if max_rows is None else max(1, max_rows)
    raw_rows: List[List[Any]] = []
    for row_idx in range(min(worksheet.nrows, limit + (1 if has_header else 0))):
        raw_rows.append(worksheet.row_values(row_idx))

    if has_header and raw_rows:
        header = [str(col) for col in raw_rows[0]]
        data_rows = raw_rows[1:]
    else:
        header = [f"column_{idx+1}" for idx in range(len(raw_rows[0]))] if raw_rows else []
        data_rows = raw_rows

    data = [
        {header[idx]: row[idx] if idx < len(row) else None for idx in range(len(header))}
        for row in data_rows
    ]

    return {
        "sheet": worksheet.name,
        "rows": data,
        "columns": header,
        "row_count": len(data),
        "file": str(path),
    }
