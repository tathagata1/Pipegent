import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import List, Optional

from agents.workflow_models import WorkflowRecord


class JsonPlanRepository:
    """Atomic JSON persistence, one workflow file per workflow ID."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def save(self, workflow: WorkflowRecord) -> None:
        target = self.root / f"{workflow.id}.json"
        payload = json.dumps(workflow.to_dict(), ensure_ascii=False, indent=2)
        with self._lock:
            fd, temporary = tempfile.mkstemp(
                prefix=f".{workflow.id}.", suffix=".tmp", dir=str(self.root)
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

    def get(self, workflow_id: str) -> Optional[WorkflowRecord]:
        target = self.root / f"{workflow_id}.json"
        try:
            return WorkflowRecord.from_dict(json.loads(target.read_text(encoding="utf-8")))
        except FileNotFoundError:
            return None

    def find_active_by_session(self, session_id: str) -> Optional[WorkflowRecord]:
        terminal = {"COMPLETED", "BLOCKED", "FAILED", "CANCELLED"}
        candidates: List[WorkflowRecord] = []
        for path in self.root.glob("*.json"):
            try:
                item = WorkflowRecord.from_dict(
                    json.loads(path.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            if item.session_id == session_id and item.state.value not in terminal:
                candidates.append(item)
        return max(candidates, key=lambda item: item.updated_at) if candidates else None
