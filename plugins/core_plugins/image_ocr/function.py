from pathlib import Path
from typing import Dict, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _resolve(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    else:
        path = path.resolve()
    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"Image path '{path}' is outside the project root.") from exc
    return path


def image_ocr(
    image_path: str,
    language: Optional[str] = "eng",
    tesseract_cmd: Optional[str] = None,
) -> Dict[str, str]:
    path = _resolve(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    try:
        import pytesseract
    except ImportError as exc:
        raise ImportError("image_ocr plugin requires the 'pytesseract' package.") from exc

    try:
        from PIL import Image
    except ImportError as exc:
        raise ImportError("image_ocr plugin requires the 'Pillow' package.") from exc

    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    with Image.open(path) as img:
        text = pytesseract.image_to_string(img, lang=language or "eng")

    return {
        "text": text.strip(),
        "language": language or "eng",
        "image": str(path),
    }
