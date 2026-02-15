import zipfile
from pathlib import Path
from typing import Dict, List, Optional


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
        raise ValueError(f"Path '{path}' is outside the project root.") from exc
    return path


def archive_manager(
    action: str,
    archive_path: str,
    source_paths: Optional[List[str]] = None,
    extract_to: Optional[str] = None,
    overwrite: bool = False,
) -> Dict[str, str]:
    action = action.lower().strip()
    archive = _resolve(archive_path)

    if action == "zip":
        if not source_paths:
            raise ValueError("source_paths is required when creating an archive.")
        for src in source_paths:
            resolved = _resolve(src)
            if not resolved.exists():
                raise FileNotFoundError(f"Source path does not exist: {resolved}")
        archive.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
            for src in source_paths:
                resolved = _resolve(src)
                arcname = resolved.relative_to(PROJECT_ROOT)
                zipf.write(resolved, arcname.as_posix())
        return {"status": "created", "archive": str(archive)}

    if action == "unzip":
        if not archive.exists() or not archive.is_file():
            raise FileNotFoundError(f"Archive not found: {archive}")
        if not extract_to:
            raise ValueError("extract_to is required when extracting.")
        destination = _resolve(extract_to)
        destination.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(archive, "r") as zipf:
            members = zipf.namelist()
            if not overwrite:
                for member in members:
                    target_path = (destination / member).resolve()
                    if not str(target_path).startswith(str(destination)):
                        raise ValueError(f"Archive entry '{member}' escapes extraction directory.")
                    if target_path.exists():
                        raise FileExistsError(
                            f"Extraction aborted: '{target_path}' already exists (set overwrite=true to replace)."
                        )

            for member in members:
                member_path = (destination / member).resolve()
                if not str(member_path).startswith(str(destination)):
                    raise ValueError(f"Archive entry '{member}' escapes extraction directory.")
            zipf.extractall(destination)
        return {"status": "extracted", "archive": str(archive), "destination": str(destination)}

    raise ValueError("action must be either 'zip' or 'unzip'")
