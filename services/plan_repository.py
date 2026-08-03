import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import Dict, Iterable, List, Optional

from agents.workflow_models import WorkflowRecord


class JsonPlanRepository:
    """Atomic JSON persistence, one workflow file per workflow ID."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._cache: Dict[str, WorkflowRecord] = {}
        self._loaded_all = False

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
                self._cache[workflow.id] = workflow
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

    def get(self, workflow_id: str) -> Optional[WorkflowRecord]:
        with self._lock:
            cached = self._cache.get(workflow_id)
            if cached is not None:
                return cached
        target = self.root / f"{workflow_id}.json"
        try:
            workflow = WorkflowRecord.from_dict(
                json.loads(target.read_text(encoding="utf-8"))
            )
            with self._lock:
                self._cache[workflow.id] = workflow
            return workflow
        except FileNotFoundError:
            return None

    def _all(self) -> Iterable[WorkflowRecord]:
        with self._lock:
            if self._loaded_all:
                return tuple(self._cache.values())
            for path in self.root.glob("*.json"):
                if path.stem in self._cache:
                    continue
                try:
                    item = WorkflowRecord.from_dict(
                        json.loads(path.read_text(encoding="utf-8"))
                    )
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    continue
                self._cache[item.id] = item
            self._loaded_all = True
            return tuple(self._cache.values())

    def find_active_by_session(self, session_id: str) -> Optional[WorkflowRecord]:
        terminal = {"COMPLETED", "BLOCKED", "FAILED", "CANCELLED"}
        candidates: List[WorkflowRecord] = []
        for item in self._all():
            if item.session_id == session_id and item.state.value not in terminal:
                candidates.append(item)
        return max(candidates, key=lambda item: item.updated_at) if candidates else None

    def find_latest_completed_by_session(
        self, session_id: str, *, exclude_workflow_id: Optional[str] = None,
    ) -> Optional[WorkflowRecord]:
        """Return recent successful context for a continuing CLI session."""
        candidates: List[WorkflowRecord] = []
        for item in self._all():
            if (
                item.session_id == session_id
                and item.state.value == "COMPLETED"
                and item.id != exclude_workflow_id
            ):
                candidates.append(item)
        return max(candidates, key=lambda item: item.updated_at) if candidates else None
