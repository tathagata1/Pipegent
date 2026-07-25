from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory.domain import (
    IndexState, MemoryRecord, MemoryScope, MemorySource, MemoryStatus, MemoryType,
    UserMemorySettings,
)


class MemoryRepository:
    """Canonical SQLite store. Vector storage is deliberately not authoritative."""

    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.initialise()

    def initialise(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT,
                agent_id TEXT, session_id TEXT, project_id TEXT, scope TEXT NOT NULL,
                memory_type TEXT NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL,
                title TEXT NOT NULL, content TEXT NOT NULL, searchable_text TEXT NOT NULL,
                confidence REAL NOT NULL, importance REAL NOT NULL,
                sensitivity TEXT NOT NULL, requires_confirmation INTEGER NOT NULL,
                tags_json TEXT NOT NULL, entities_json TEXT NOT NULL,
                source_message_ids_json TEXT NOT NULL, source_document_id TEXT,
                source_chunk_id TEXT, valid_from TEXT, valid_until TEXT,
                last_accessed_at TEXT, access_count INTEGER NOT NULL DEFAULT 0,
                supersedes_memory_id TEXT, superseded_by_memory_id TEXT,
                embedding_model TEXT, embedding_version TEXT, index_state TEXT NOT NULL,
                metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_memories_owner
                ON memories(tenant_id, user_id, scope, status);
            CREATE INDEX IF NOT EXISTS idx_memories_document
                ON memories(tenant_id, source_document_id);
            CREATE TABLE IF NOT EXISTS memory_revisions (
                revision_id INTEGER PRIMARY KEY AUTOINCREMENT, memory_id TEXT NOT NULL,
                snapshot_json TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memory_operations (
                operation_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE,
                tenant_id TEXT NOT NULL, user_id TEXT, action TEXT NOT NULL,
                status TEXT NOT NULL, result_json TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memory_access_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, memory_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL, user_id TEXT, operation TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS user_memory_settings (
                tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
                settings_json TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(tenant_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT,
                project_id TEXT, title TEXT NOT NULL, filename TEXT NOT NULL,
                source_type TEXT NOT NULL, checksum TEXT NOT NULL,
                metadata_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(tenant_id, checksum)
            );
            """)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def save(self, record: MemoryRecord, revision_reason: str = "create") -> None:
        data = self._serialize(record)
        columns = ", ".join(data)
        placeholders = ", ".join("?" for _ in data)
        updates = ", ".join(f"{key}=excluded.{key}" for key in data if key != "id")
        with self._lock, self._connection:
            existing = self.get(record.id)
            if existing:
                self._connection.execute(
                    "INSERT INTO memory_revisions(memory_id,snapshot_json,reason,created_at)"
                    " VALUES(?,?,?,?)",
                    (record.id, json.dumps(self._serialize(existing)), revision_reason,
                     datetime.now().astimezone().isoformat()),
                )
            self._connection.execute(
                f"INSERT INTO memories ({columns}) VALUES ({placeholders}) "
                f"ON CONFLICT(id) DO UPDATE SET {updates}", tuple(data.values())
            )

    def get(self, memory_id: str) -> Optional[MemoryRecord]:
        row = self._connection.execute(
            "SELECT * FROM memories WHERE id=?", (memory_id,)
        ).fetchone()
        return self._deserialize(row) if row else None

    def list(
        self, *, tenant_id: str, user_id: Optional[str], scopes: Optional[List[MemoryScope]] = None,
        session_id: Optional[str] = None, project_id: Optional[str] = None,
        agent_id: Optional[str] = None, include_inactive: bool = False,
        document_id: Optional[str] = None,
    ) -> List[MemoryRecord]:
        clauses, values = ["tenant_id=?"], [tenant_id]
        if not include_inactive:
            clauses.append("status=?")
            values.append(MemoryStatus.ACTIVE.value)
        if scopes:
            clauses.append("scope IN (%s)" % ",".join("?" for _ in scopes))
            values.extend(scope.value for scope in scopes)
        # Personal records can only be seen by their owner; shared records have NULL user.
        clauses.append("(user_id IS NULL OR user_id=?)")
        values.append(user_id)
        if session_id is not None:
            clauses.append("(scope != ? OR session_id=?)")
            values.extend([MemoryScope.SESSION.value, session_id])
        if project_id is not None:
            clauses.append("(project_id IS NULL OR project_id=?)")
            values.append(project_id)
        if agent_id is not None:
            clauses.append("(scope != ? OR agent_id=?)")
            values.extend([MemoryScope.AGENT.value, agent_id])
        if document_id is not None:
            clauses.append("source_document_id=?")
            values.append(document_id)
        rows = self._connection.execute(
            "SELECT * FROM memories WHERE " + " AND ".join(clauses)
            + " ORDER BY created_at DESC", values
        ).fetchall()
        return [self._deserialize(row) for row in rows]

    def find_similar_text(
        self, text: str, *, tenant_id: str, user_id: Optional[str], scope: MemoryScope,
        session_id: Optional[str], project_id: Optional[str],
    ) -> List[MemoryRecord]:
        needle = " ".join(text.casefold().split())
        return [
            item for item in self.list(
                tenant_id=tenant_id, user_id=user_id, scopes=[scope],
                session_id=session_id, project_id=project_id,
            )
            if " ".join(item.content.casefold().split()) == needle
        ]

    def list_pending_index(self, embedding_model: str) -> List[MemoryRecord]:
        rows = self._connection.execute(
            "SELECT * FROM memories WHERE status=? AND "
            "(index_state!=? OR embedding_model IS NULL OR embedding_model!=?)",
            (MemoryStatus.ACTIVE.value, IndexState.INDEXED.value, embedding_model),
        ).fetchall()
        return [self._deserialize(row) for row in rows]

    def mark_deleted(self, record: MemoryRecord) -> None:
        record.status = MemoryStatus.DELETED
        record.index_state = IndexState.NOT_REQUIRED
        record.updated_at = datetime.now(record.updated_at.tzinfo)
        self.save(record, "delete")
        self.audit(record.id, record.tenant_id, record.user_id, "delete")

    def audit(
        self, memory_id: str, tenant_id: str, user_id: Optional[str], operation: str,
    ) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO memory_access_log(memory_id,tenant_id,user_id,operation,created_at)"
                " VALUES(?,?,?,?,?)",
                (memory_id, tenant_id, user_id, operation,
                 datetime.now().astimezone().isoformat()),
            )

    def get_settings(self, tenant_id: str, user_id: str) -> UserMemorySettings:
        row = self._connection.execute(
            "SELECT settings_json FROM user_memory_settings WHERE tenant_id=? AND user_id=?",
            (tenant_id, user_id),
        ).fetchone()
        return UserMemorySettings(**json.loads(row[0])) if row else UserMemorySettings()

    def save_settings(
        self, tenant_id: str, user_id: str, settings: UserMemorySettings,
    ) -> None:
        now = datetime.now().astimezone().isoformat()
        with self._connection:
            self._connection.execute(
                "INSERT INTO user_memory_settings VALUES(?,?,?,?) "
                "ON CONFLICT(tenant_id,user_id) DO UPDATE SET "
                "settings_json=excluded.settings_json,updated_at=excluded.updated_at",
                (tenant_id, user_id, json.dumps(asdict(settings)), now),
            )

    def save_document(
        self, *, document_id: str, tenant_id: str, user_id: Optional[str],
        project_id: Optional[str], title: str, filename: str, source_type: str,
        checksum: str, metadata: Dict[str, Any],
    ) -> None:
        now = datetime.now().astimezone().isoformat()
        with self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO documents VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (document_id, tenant_id, user_id, project_id, title, filename,
                 source_type, checksum, json.dumps(metadata), now, now),
            )

    def delete_document(
        self, document_id: str, tenant_id: str, user_id: Optional[str],
    ) -> None:
        with self._connection:
            self._connection.execute(
                "DELETE FROM documents WHERE id=? AND tenant_id=? "
                "AND (user_id IS NULL OR user_id=?)",
                (document_id, tenant_id, user_id),
            )

    def begin_operation(
        self, operation_id: str, idempotency_key: Optional[str], tenant_id: str,
        user_id: Optional[str], action: str,
    ) -> Optional[Dict[str, Any]]:
        if idempotency_key:
            row = self._connection.execute(
                "SELECT operation_id,result_json FROM memory_operations "
                "WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if row and row["result_json"]:
                return json.loads(row["result_json"])
            if row:
                # A process interruption may leave an operation permanently in
                # "started". Transfer the stable key to this retry so its result
                # can be completed and cached normally.
                with self._connection:
                    self._connection.execute(
                        "UPDATE memory_operations SET operation_id=?,status=? "
                        "WHERE idempotency_key=?",
                        (operation_id, "restarted", idempotency_key),
                    )
                return None
        with self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO memory_operations VALUES(?,?,?,?,?,?,?,?)",
                (operation_id, idempotency_key, tenant_id, user_id, action, "started", None,
                 datetime.now().astimezone().isoformat()),
            )
        return None

    def finish_operation(self, operation_id: str, status: str, result: Dict[str, Any]) -> None:
        with self._connection:
            self._connection.execute(
                "UPDATE memory_operations SET status=?,result_json=? WHERE operation_id=?",
                (status, json.dumps(result, default=str), operation_id),
            )

    @staticmethod
    def _serialize(record: MemoryRecord) -> Dict[str, Any]:
        return {
            "id": record.id, "tenant_id": record.tenant_id, "user_id": record.user_id,
            "agent_id": record.agent_id, "session_id": record.session_id,
            "project_id": record.project_id, "scope": record.scope.value,
            "memory_type": record.memory_type.value, "source": record.source.value,
            "status": record.status.value, "title": record.title,
            "content": record.content, "searchable_text": record.searchable_text,
            "confidence": record.confidence, "importance": record.importance,
            "sensitivity": record.sensitivity,
            "requires_confirmation": int(record.requires_confirmation),
            "tags_json": json.dumps(record.tags), "entities_json": json.dumps(record.entities),
            "source_message_ids_json": json.dumps(record.source_message_ids),
            "source_document_id": record.source_document_id,
            "source_chunk_id": record.source_chunk_id,
            "valid_from": record.valid_from.isoformat() if record.valid_from else None,
            "valid_until": record.valid_until.isoformat() if record.valid_until else None,
            "last_accessed_at": (
                record.last_accessed_at.isoformat() if record.last_accessed_at else None
            ),
            "access_count": record.access_count,
            "supersedes_memory_id": record.supersedes_memory_id,
            "superseded_by_memory_id": record.superseded_by_memory_id,
            "embedding_model": record.embedding_model,
            "embedding_version": record.embedding_version,
            "index_state": record.index_state.value,
            "metadata_json": json.dumps(record.metadata),
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
        }

    @staticmethod
    def _deserialize(row: sqlite3.Row) -> MemoryRecord:
        dt = lambda value: datetime.fromisoformat(value) if value else None
        return MemoryRecord(
            id=row["id"], tenant_id=row["tenant_id"], user_id=row["user_id"],
            agent_id=row["agent_id"], session_id=row["session_id"],
            project_id=row["project_id"], scope=MemoryScope(row["scope"]),
            memory_type=MemoryType(row["memory_type"]), source=MemorySource(row["source"]),
            status=MemoryStatus(row["status"]), title=row["title"], content=row["content"],
            searchable_text=row["searchable_text"], confidence=row["confidence"],
            importance=row["importance"], sensitivity=row["sensitivity"],
            requires_confirmation=bool(row["requires_confirmation"]),
            tags=json.loads(row["tags_json"]), entities=json.loads(row["entities_json"]),
            source_message_ids=json.loads(row["source_message_ids_json"]),
            source_document_id=row["source_document_id"], source_chunk_id=row["source_chunk_id"],
            valid_from=dt(row["valid_from"]), valid_until=dt(row["valid_until"]),
            last_accessed_at=dt(row["last_accessed_at"]), access_count=row["access_count"],
            supersedes_memory_id=row["supersedes_memory_id"],
            superseded_by_memory_id=row["superseded_by_memory_id"],
            embedding_model=row["embedding_model"], embedding_version=row["embedding_version"],
            index_state=IndexState(row["index_state"]), metadata=json.loads(row["metadata_json"]),
            created_at=dt(row["created_at"]), updated_at=dt(row["updated_at"]),
        )
