from typing import Dict, Optional

from services.path_utils import resolve_user_file


def image_ocr(
    image_path: str,
    language: Optional[str] = "eng",
    tesseract_cmd: Optional[str] = None,
) -> Dict[str, str]:
    path = resolve_user_file(
        image_path,
        expected_extensions=(".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".pdf"),
    )

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
