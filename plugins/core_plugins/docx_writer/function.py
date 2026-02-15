from pathlib import Path
from typing import Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _resolve_destination(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    else:
        path = path.resolve()
    if path.suffix.lower() != ".docx":
        raise ValueError("docx_writer only writes .docx files.")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def docx_writer(
    file_path: str,
    paragraphs: List[Dict[str, str]],
    overwrite: bool = False,
) -> Dict[str, str]:
    if not paragraphs:
        raise ValueError("paragraphs must include at least one entry.")

    try:
        from docx import Document  # type: ignore
    except ImportError as exc:
        raise ImportError("docx_writer requires the 'python-docx' package.") from exc

    target = _resolve_destination(file_path)
    if target.exists() and not overwrite:
        raise FileExistsError(f"File already exists (set overwrite=true to replace): {target}")

    document = Document()
    for item in paragraphs:
        text = item.get("text")
        if not text:
            continue
        style: Optional[str] = item.get("style")
        paragraph = document.add_paragraph(text)
        if style:
            paragraph.style = style

    document.save(target)
    return {"status": "written", "path": str(target), "paragraphs": str(len(paragraphs))}
