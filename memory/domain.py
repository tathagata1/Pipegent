from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryType(str, Enum):
    USER_FACT = "user_fact"
    USER_PREFERENCE = "user_preference"
    PROJECT_FACT = "project_fact"
    DECISION = "decision"
    TASK_OUTCOME = "task_outcome"
    PROCEDURE = "procedure"
    OBSERVATION = "observation"
    CORRECTION = "correction"
    DOCUMENT_CHUNK = "document_chunk"


class MemorySource(str, Enum):
    USER_EXPLICIT = "user_explicit"
    USER_IMPLICIT = "user_implicit"
    AGENT_INFERRED = "agent_inferred"
    EXECUTION_RESULT = "execution_result"
    IMPORTED_DOCUMENT = "imported_document"
    SYSTEM = "system"


class MemoryStatus(str, Enum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DELETED = "deleted"
    REJECTED = "rejected"


class IndexState(str, Enum):
    PENDING = "pending"
    INDEXED = "indexed"
    FAILED = "failed"
    NOT_REQUIRED = "not_required"


class MemoryScope(str, Enum):
    USER = "user"
    SESSION = "session"
    PROJECT = "project"
    AGENT = "agent"
    ORGANISATION = "organisation"
    KNOWLEDGE_BASE = "knowledge_base"


class MemoryDecision(str, Enum):
    STORE = "store"
    REQUEST_CONFIRMATION = "request_confirmation"
    IGNORE = "ignore"
    REJECT = "reject"


class MemoryAction(str, Enum):
    SEARCH = "search"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    SUPERSEDE = "supersede"
    LIST = "list"
    INGEST_DOCUMENT = "ingest_document"
    REMOVE_DOCUMENT = "remove_document"
    REINDEX = "reindex"
    EXPORT = "export"
    CONSOLIDATE = "consolidate"


@dataclass
class MemoryCandidate:
    content: str
    proposed_type: MemoryType
    proposed_scope: MemoryScope
    source: MemorySource
    reason: str
    confidence: float = 1.0
    importance: float = 0.7
    estimated_lifetime: str = "long_term"
    sensitivity: str = "normal"
    requires_confirmation: bool = False
    source_message_ids: List[str] = field(default_factory=list)
    title: str = ""
    tags: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryRecord:
    id: str
    tenant_id: str
    user_id: Optional[str]
    agent_id: Optional[str]
    session_id: Optional[str]
    project_id: Optional[str]
    scope: MemoryScope
    memory_type: MemoryType
    source: MemorySource
    status: MemoryStatus
    title: str
    content: str
    searchable_text: str
    confidence: float
    importance: float
    sensitivity: str
    requires_confirmation: bool
    tags: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    source_message_ids: List[str] = field(default_factory=list)
    source_document_id: Optional[str] = None
    source_chunk_id: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    last_accessed_at: Optional[datetime] = None
    access_count: int = 0
    supersedes_memory_id: Optional[str] = None
    superseded_by_memory_id: Optional[str] = None
    embedding_model: Optional[str] = None
    embedding_version: Optional[str] = None
    index_state: IndexState = IndexState.PENDING
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def vector_payload(self) -> Dict[str, Any]:
        return {
            "memory_id": self.id, "tenant_id": self.tenant_id,
            "user_id": self.user_id or "", "agent_id": self.agent_id or "",
            "session_id": self.session_id or "", "project_id": self.project_id or "",
            "scope": self.scope.value, "memory_type": self.memory_type.value,
            "source": self.source.value, "status": self.status.value,
            "tags": self.tags, "sensitivity": self.sensitivity,
            "created_at": self.created_at.isoformat(),
            "valid_from": self.valid_from.isoformat() if self.valid_from else "",
            "valid_until": self.valid_until.isoformat() if self.valid_until else "",
        }


@dataclass
class RetrievedMemory:
    memory_id: str
    content: str
    memory_type: MemoryType
    source: MemorySource
    scope: MemoryScope
    semantic_score: float
    final_score: float
    confidence: float
    importance: float
    created_at: datetime
    valid_until: Optional[datetime]
    citation_label: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UserMemorySettings:
    memory_enabled: bool = True
    retrieval_enabled: bool = True
    automatic_storage_enabled: bool = False
    confirmation_required_for_inferred_memory: bool = True
    retention_days: Optional[int] = None


@dataclass
class MemoryPolicyInput:
    candidate: MemoryCandidate
    automatic_memory_enabled: bool
    explicit_user_request: bool
    user_consent_required: bool = True
    existing_conflicts: List[MemoryRecord] = field(default_factory=list)


@dataclass
class MemoryPolicyResult:
    decision: MemoryDecision
    reasons: List[str]
    normalised_candidate: Optional[MemoryCandidate] = None


@dataclass
class MemoryOperationRequest:
    operation_id: str
    action: MemoryAction
    tenant_id: str
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    project_id: Optional[str] = None
    query: Optional[str] = None
    memory: Optional[MemoryCandidate] = None
    memory_id: Optional[str] = None
    document_path: Optional[str] = None
    top_k: int = 8
    filters: Dict[str, Any] = field(default_factory=dict)
    idempotency_key: Optional[str] = None
    explicit_user_request: bool = False


@dataclass
class MemoryOperationResult:
    operation_id: str
    action: MemoryAction
    status: str
    records: List[MemoryRecord] = field(default_factory=list)
    retrieved: List[RetrievedMemory] = field(default_factory=list)
    created_memory_id: Optional[str] = None
    updated_memory_id: Optional[str] = None
    deleted_memory_id: Optional[str] = None
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
