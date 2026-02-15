import os
from pathlib import Path
from typing import Optional


def clear_context(reason: Optional[str] = None) -> str:
    context_path_str = os.getenv("PIPEGENT_CONTEXT_FILE")
    if not context_path_str:
        raise RuntimeError("Context file location is not configured.")

    context_path = Path(context_path_str)
    context_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        context_path.unlink()
    except FileNotFoundError:
        pass
    context_path.write_text("[]", encoding="utf-8")

    suffix = f" Reason: {reason}" if reason else ""
    return f"Context history reset ({context_path.name}).{suffix}"
