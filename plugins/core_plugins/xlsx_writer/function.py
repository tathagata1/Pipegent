from pathlib import Path
from typing import List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _resolve_destination(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    else:
        path = path.resolve()
    if path.suffix.lower() != ".xlsx":
        raise ValueError("xlsx_writer only outputs .xlsx files.")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def xlsx_writer(
    file_path: str,
    rows: List[List],
    headers: Optional[List[str]] = None,
    sheet_name: Optional[str] = None,
    overwrite: bool = False,
) -> dict:
    if not rows and not headers:
        raise ValueError("Provide at least one row or header to write.")

    try:
        from openpyxl import Workbook  # type: ignore
    except ImportError as exc:
        raise ImportError("xlsx_writer requires the 'openpyxl' package.") from exc

    target = _resolve_destination(file_path)
    if target.exists() and not overwrite:
        raise FileExistsError(f"File already exists (set overwrite=true to replace): {target}")

    wb = Workbook()
    ws = wb.active
    if sheet_name:
        ws.title = sheet_name

    if headers:
        ws.append(headers)
    for row in rows:
        ws.append(list(row))

    wb.save(target)
    return {
        "status": "written",
        "path": str(target),
        "rows_written": len(rows),
        "has_headers": bool(headers),
    }
