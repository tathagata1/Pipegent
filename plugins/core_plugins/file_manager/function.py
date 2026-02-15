import shutil
from pathlib import Path
from typing import Dict, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _resolve_within_repo(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    else:
        path = path.resolve()
    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"Path '{path}' is outside the project root.") from exc
    return path


def file_manager(
    action: str,
    source_path: Optional[str] = None,
    destination_path: Optional[str] = None,
    force: bool = False,
) -> Dict[str, str]:
    action = action.lower().strip()
    if action not in {"copy", "move", "delete"}:
        raise ValueError("action must be one of: copy, move, delete")

    if action in {"copy", "move"}:
        if not source_path or not destination_path:
            raise ValueError("source_path and destination_path are required for copy/move")
        source = _resolve_within_repo(source_path)
        destination = _resolve_within_repo(destination_path)

        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"Source file does not exist: {source}")

        dest_parent = destination.parent
        dest_parent.mkdir(parents=True, exist_ok=True)

        if destination.exists():
            if not force:
                raise FileExistsError(f"Destination already exists: {destination}")
            if destination.is_dir():
                raise IsADirectoryError(f"Destination is a directory: {destination}")

        if action == "copy":
            shutil.copy2(source, destination)
            return {"status": "copied", "source": str(source), "destination": str(destination)}
        shutil.move(str(source), str(destination))
        return {"status": "moved", "source": str(source), "destination": str(destination)}

    # delete action
    if not source_path:
        raise ValueError("source_path is required for delete")
    target = _resolve_within_repo(source_path)
    if not target.exists():
        raise FileNotFoundError(f"Target does not exist: {target}")
    if target.is_dir():
        raise IsADirectoryError(f"Deletion is limited to files. '{target}' is a directory.")

    target.unlink()
    return {"status": "deleted", "target": str(target)}
