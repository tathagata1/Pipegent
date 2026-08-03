from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Optional

from memory.domain import (
    IndexState, MemoryAction, MemoryCandidate, MemoryDecision, MemoryOperationRequest,
    MemoryOperationResult, MemoryPolicyInput, MemoryRecord, MemoryScope, MemorySource,
    MemoryStatus, MemoryType,
)
from memory.embeddings import EmbeddingProvider
from memory.policy import MemoryPolicyEngine
from memory.repository import MemoryRepository
from memory.retrieval import MemoryRetriever, RetrievalContextBuilder
from memory.vector_store import VectorRecord, VectorStore
from services.observability import log_event

logger = logging.getLogger(__name__)


class MemoryService:
    def __init__(
        self, repository: MemoryRepository, embeddings: EmbeddingProvider,
        vector_store: VectorStore, policy: Optional[MemoryPolicyEngine] = None,
        retriever: Optional[MemoryRetriever] = None,
        context_builder: Optional[RetrievalContextBuilder] = None,
        reconcile_on_startup: bool = True,
    ) -> None:
        self.repository, self.embeddings, self.vector_store = (
            repository, embeddings, vector_store
        )
        self.policy = policy or MemoryPolicyEngine()
        self.retriever = retriever or MemoryRetriever(
            repository, embeddings, vector_store
        )
        self.context_builder = context_builder or RetrievalContextBuilder()
        self._vector_store_ready = False
        try:
            self._ensure_vector_store()
        except Exception:
            # SQLite is the canonical store. Keep memory available when the
            # replaceable vector index starts late, and reconnect on demand.
            logger.exception("vector_store_startup_unavailable")
        if reconcile_on_startup and self._vector_store_ready:
            self._reconcile_pending()

    def _ensure_vector_store(self) -> None:
        if not self._vector_store_ready:
            self.vector_store.initialise()
            self._vector_store_ready = True

    def execute(self, request: MemoryOperationRequest) -> MemoryOperationResult:
        started = perf_counter()
        log_event(
            logger, "memory.operation.request", operation_id=request.operation_id,
            action=request.action, request=request,
        )
        cached = self.repository.begin_operation(
            request.operation_id, request.idempotency_key, request.tenant_id,
            request.user_id, request.action.value,
        )
        if cached:
            result = MemoryOperationResult(
                operation_id=request.operation_id, action=request.action,
                status=cached.get("status", "success"),
                created_memory_id=cached.get("created_memory_id"),
                updated_memory_id=cached.get("updated_memory_id"),
                deleted_memory_id=cached.get("deleted_memory_id"),
                evidence=cached.get("evidence", []), warnings=cached.get("warnings", []),
                errors=cached.get("errors", []),
            )
            log_event(
                logger, "memory.operation.cached", operation_id=request.operation_id,
                action=request.action, result=result,
                elapsed_ms=round((perf_counter() - started) * 1000, 2),
            )
            return result
        try:
            if request.action == MemoryAction.CREATE:
                result = self._create(request)
            elif request.action == MemoryAction.SEARCH:
                result = self._search(request)
            elif request.action == MemoryAction.LIST:
                result = self._list(request)
            elif request.action == MemoryAction.DELETE:
                result = self._delete(request)
            elif request.action in {MemoryAction.UPDATE, MemoryAction.SUPERSEDE}:
                result = self._update(request)
            elif request.action == MemoryAction.REINDEX:
                result = self.reindex(request)
            elif request.action == MemoryAction.EXPORT:
                result = self._export(request)
            elif request.action == MemoryAction.REMOVE_DOCUMENT:
                result = self.remove_document(request)
            elif request.action == MemoryAction.CONSOLIDATE:
                result = self.consolidate(request)
            else:
                raise ValueError(f"Unsupported memory action: {request.action.value}")
        except Exception as exc:
            logger.exception(
                "memory_operation_failed operation_id=%s tenant_id=%s action=%s",
                request.operation_id, request.tenant_id, request.action.value,
            )
            result = MemoryOperationResult(
                request.operation_id, request.action, "failed",
                errors=[{"code": type(exc).__name__, "message": str(exc)}],
            )
        self.repository.finish_operation(request.operation_id, result.status, {
            "status": result.status, "created_memory_id": result.created_memory_id,
            "updated_memory_id": result.updated_memory_id,
            "deleted_memory_id": result.deleted_memory_id,
            "evidence": result.evidence, "warnings": result.warnings,
            "errors": result.errors,
        })
        elapsed_ms = round((perf_counter() - started) * 1000, 2)
        log_event(
            logger, "memory.operation.result", operation_id=request.operation_id,
            action=request.action, status=result.status, result=result,
            elapsed_ms=elapsed_ms,
        )
        logger.info(
            "Memory operation completed operation_id=%s action=%s status=%s "
            "elapsed_ms=%.2f",
            request.operation_id, request.action.value, result.status, elapsed_ms,
        )
        return result

    def _create(self, request: MemoryOperationRequest) -> MemoryOperationResult:
        if request.memory is None:
            raise ValueError("CREATE requires a memory candidate.")
        settings = (
            self.repository.get_settings(request.tenant_id, request.user_id)
            if request.user_id else None
        )
        if settings and not settings.memory_enabled:
            return MemoryOperationResult(
                request.operation_id, request.action, "rejected",
                warnings=["Memory is disabled for this user."],
            )
        duplicates = self.repository.find_similar_text(
            request.memory.content, tenant_id=request.tenant_id, user_id=request.user_id,
            scope=request.memory.proposed_scope, session_id=request.session_id,
            project_id=request.project_id,
        )
        decision = self.policy.evaluate(MemoryPolicyInput(
            request.memory,
            automatic_memory_enabled=bool(
                settings.automatic_storage_enabled if settings else False
            ),
            explicit_user_request=request.explicit_user_request,
            existing_conflicts=duplicates,
        ))
        log_event(
            logger, "memory.policy.decision", operation_id=request.operation_id,
            candidate=request.memory, duplicate_ids=[item.id for item in duplicates],
            decision=decision,
        )
        if duplicates:
            duplicate = duplicates[0]
            if (
                duplicate.index_state != IndexState.INDEXED
                or duplicate.embedding_model != self.embeddings.model_name
            ):
                indexed, warning = self._index_record(duplicate)
                return MemoryOperationResult(
                    request.operation_id, request.action,
                    "success" if indexed else "partial_success",
                    records=[duplicate], created_memory_id=duplicate.id,
                    evidence=[{
                        "type": "duplicate_reconciled",
                        "memory_id": duplicate.id, "persisted": True,
                        "indexed": indexed,
                    }],
                    warnings=[] if indexed else [warning],
                )
            return MemoryOperationResult(
                request.operation_id, request.action, "success",
                records=[duplicate], created_memory_id=duplicate.id,
                evidence=[{"type": "duplicate", "memory_id": duplicate.id,
                           "persisted": True, "indexed": True}],
            )
        if decision.decision != MemoryDecision.STORE or decision.normalised_candidate is None:
            return MemoryOperationResult(
                request.operation_id, request.action, decision.decision.value,
                warnings=decision.reasons,
            )
        candidate = decision.normalised_candidate
        now = datetime.now(timezone.utc)
        record = MemoryRecord(
            id=uuid.uuid4().hex, tenant_id=request.tenant_id, user_id=request.user_id,
            agent_id=request.agent_id, session_id=(
                request.session_id if candidate.proposed_scope == MemoryScope.SESSION else None
            ),
            project_id=(
                request.project_id if candidate.proposed_scope == MemoryScope.PROJECT else None
            ),
            scope=candidate.proposed_scope, memory_type=candidate.proposed_type,
            source=candidate.source, status=MemoryStatus.ACTIVE,
            title=candidate.title or candidate.content[:80],
            content=candidate.content,
            searchable_text=" ".join(
                [candidate.title, candidate.content, *candidate.tags, *candidate.entities]
            ).strip(),
            confidence=candidate.confidence, importance=candidate.importance,
            sensitivity=candidate.sensitivity,
            requires_confirmation=candidate.requires_confirmation,
            tags=candidate.tags, entities=candidate.entities,
            source_message_ids=candidate.source_message_ids,
            valid_from=candidate.valid_from, valid_until=candidate.valid_until,
            embedding_model=self.embeddings.model_name, embedding_version="1",
            metadata=candidate.metadata, created_at=now, updated_at=now,
        )
        self.repository.save(record)
        indexed, warning = self._index_record(record)
        if indexed:
            status, warnings = "success", []
        else:
            status, warnings = "partial_success", [warning]
            logger.warning(
                "memory_index_pending operation_id=%s memory_id=%s",
                request.operation_id, record.id,
            )
        return MemoryOperationResult(
            request.operation_id, request.action, status, records=[record],
            created_memory_id=record.id,
            evidence=[{"type": "canonical_record", "memory_id": record.id,
                       "persisted": True, "indexed": record.index_state == IndexState.INDEXED}],
            warnings=warnings,
        )

    def _index_record(self, record: MemoryRecord) -> tuple[bool, str]:
        try:
            self._ensure_vector_store()
            vector = self.embeddings.embed_query(record.searchable_text)
            record.embedding_model = self.embeddings.model_name
            self.vector_store.upsert([
                VectorRecord(record.id, vector, record.vector_payload())
            ])
            record.index_state = IndexState.INDEXED
            record.metadata.pop("last_index_error", None)
            self.repository.save(record, "index_complete")
            return True, ""
        except Exception as exc:
            record.index_state = IndexState.PENDING
            record.metadata["last_index_error"] = type(exc).__name__
            self.repository.save(record, "index_pending")
            return (
                False,
                "Canonical memory was saved, but vector indexing is pending.",
            )

    def _reconcile_pending(self) -> None:
        """Repair canonical records left pending by interruption or dependency failure."""
        for record in self.repository.list_pending_index(self.embeddings.model_name):
            indexed, _ = self._index_record(record)
            logger.info(
                "memory_startup_reconcile memory_id=%s indexed=%s",
                record.id, indexed,
            )

    def _search(self, request: MemoryOperationRequest) -> MemoryOperationResult:
        if not request.query:
            raise ValueError("SEARCH requires a query.")
        self._ensure_vector_store()
        settings = (
            self.repository.get_settings(request.tenant_id, request.user_id)
            if request.user_id else None
        )
        if settings and (not settings.memory_enabled or not settings.retrieval_enabled):
            return MemoryOperationResult(request.operation_id, request.action, "disabled")
        scopes = self._scopes(request.filters.get("scopes"))
        retrieved = self.retriever.retrieve(
            request.query, tenant_id=request.tenant_id, user_id=request.user_id,
            session_id=request.session_id, project_id=request.project_id,
            agent_id=request.agent_id, scopes=scopes, top_k=request.top_k,
        )
        return MemoryOperationResult(
            request.operation_id, request.action, "success", retrieved=retrieved,
            evidence=[{"type": "retrieval", "result_count": len(retrieved)}],
        )

    def _list(self, request: MemoryOperationRequest) -> MemoryOperationResult:
        records = self.repository.list(
            tenant_id=request.tenant_id, user_id=request.user_id,
            scopes=self._scopes(request.filters.get("scopes")),
            session_id=request.session_id, project_id=request.project_id,
            agent_id=request.agent_id,
        )
        return MemoryOperationResult(
            request.operation_id, request.action, "success", records=records,
            evidence=[{"type": "canonical_list", "result_count": len(records)}],
        )

    def _delete(self, request: MemoryOperationRequest) -> MemoryOperationResult:
        record = self._authorised_record(request)
        self.repository.mark_deleted(record)
        self.vector_store.delete([record.id])
        return MemoryOperationResult(
            request.operation_id, request.action, "success",
            deleted_memory_id=record.id,
            evidence=[{"type": "deletion", "canonical_deleted": True,
                       "vector_deleted": True}],
        )

    def _update(self, request: MemoryOperationRequest) -> MemoryOperationResult:
        old = self._authorised_record(request)
        if request.memory is None:
            raise ValueError("UPDATE requires corrected memory content.")
        create_request = MemoryOperationRequest(
            operation_id=request.operation_id + ":replacement", action=MemoryAction.CREATE,
            tenant_id=request.tenant_id, user_id=request.user_id, agent_id=request.agent_id,
            session_id=request.session_id, project_id=request.project_id,
            memory=request.memory, idempotency_key=(
                request.idempotency_key + ":replacement" if request.idempotency_key else None
            ), explicit_user_request=request.explicit_user_request,
        )
        created = self._create(create_request)
        if not created.created_memory_id:
            return MemoryOperationResult(
                request.operation_id, request.action, created.status,
                warnings=created.warnings, errors=created.errors,
            )
        replacement = self.repository.get(created.created_memory_id)
        if replacement.id == old.id:
            return MemoryOperationResult(
                request.operation_id, request.action, "success",
                updated_memory_id=old.id,
                evidence=[{"type": "duplicate", "memory_id": old.id}],
            )
        replacement.memory_type = MemoryType.CORRECTION
        replacement.supersedes_memory_id = old.id
        old.status = MemoryStatus.SUPERSEDED
        old.superseded_by_memory_id = replacement.id
        old.updated_at = datetime.now(timezone.utc)
        self.repository.save(old, "superseded")
        self.repository.save(replacement, "correction_link")
        self.vector_store.delete([old.id])
        return MemoryOperationResult(
            request.operation_id, request.action, created.status,
            records=[replacement], updated_memory_id=replacement.id,
            evidence=created.evidence + [{
                "type": "supersession", "old_memory_id": old.id,
                "new_memory_id": replacement.id,
            }], warnings=created.warnings,
        )

    def reindex(self, request: MemoryOperationRequest) -> MemoryOperationResult:
        records = self.repository.list(
            tenant_id=request.tenant_id, user_id=request.user_id,
            scopes=self._scopes(request.filters.get("scopes")),
            session_id=request.session_id, project_id=request.project_id,
        )
        selected = [
            item for item in records if item.index_state != IndexState.INDEXED
            or item.embedding_model != self.embeddings.model_name
        ]
        failures = []
        for record in selected:
            try:
                vector = self.embeddings.embed_query(record.searchable_text)
                record.embedding_model = self.embeddings.model_name
                self.vector_store.upsert([VectorRecord(
                    record.id, vector, record.vector_payload()
                )])
                record.index_state = IndexState.INDEXED
                self.repository.save(record, "reindex")
            except Exception as exc:
                failures.append({"memory_id": record.id, "code": type(exc).__name__})
        return MemoryOperationResult(
            request.operation_id, request.action,
            "partial_success" if failures else "success",
            evidence=[{"type": "reindex", "attempted": len(selected),
                       "succeeded": len(selected) - len(failures)}],
            errors=failures,
        )

    def consolidate(self, request: MemoryOperationRequest) -> MemoryOperationResult:
        records = self.repository.list(
            tenant_id=request.tenant_id, user_id=request.user_id,
            scopes=self._scopes(request.filters.get("scopes")),
            session_id=request.session_id, project_id=request.project_id,
        )
        seen, duplicates = {}, []
        for record in records:
            key = (record.scope.value, " ".join(record.content.casefold().split()))
            if key in seen:
                record.status = MemoryStatus.SUPERSEDED
                record.superseded_by_memory_id = seen[key].id
                self.repository.save(record, "consolidate_duplicate")
                self.vector_store.delete([record.id])
                duplicates.append(record.id)
            else:
                seen[key] = record
        return MemoryOperationResult(
            request.operation_id, request.action, "success",
            evidence=[{"type": "consolidation_report",
                       "duplicates_superseded": duplicates, "permanently_deleted": 0}],
        )

    def create_document_chunks(
        self, *, document_id: str, chunks, tenant_id: str, user_id: Optional[str],
        project_id: Optional[str], title: str, filename: str, source_type: str,
        checksum: str, metadata: Dict[str, Any],
    ) -> List[str]:
        self.repository.save_document(
            document_id=document_id, tenant_id=tenant_id, user_id=user_id,
            project_id=project_id, title=title, filename=filename,
            source_type=source_type, checksum=checksum, metadata=metadata,
        )
        existing = self.repository.list(
            tenant_id=tenant_id, user_id=user_id,
            scopes=[MemoryScope.KNOWLEDGE_BASE], project_id=project_id,
            document_id=document_id,
        )
        if existing:
            return [item.id for item in existing]
        now = datetime.now(timezone.utc)
        ids = []
        for chunk in chunks:
            record = MemoryRecord(
                id=uuid.uuid4().hex, tenant_id=tenant_id, user_id=user_id,
                agent_id=None, session_id=None, project_id=project_id,
                scope=MemoryScope.KNOWLEDGE_BASE,
                memory_type=MemoryType.DOCUMENT_CHUNK,
                source=MemorySource.IMPORTED_DOCUMENT, status=MemoryStatus.ACTIVE,
                title=f"{title} — {chunk.heading or 'chunk'}", content=chunk.content,
                searchable_text=f"{title} {chunk.heading} {chunk.content}",
                confidence=1.0, importance=0.6, sensitivity="normal",
                requires_confirmation=False, source_document_id=document_id,
                source_chunk_id=chunk.chunk_id, embedding_model=self.embeddings.model_name,
                embedding_version="1", metadata={
                    **metadata, "filename": filename, "source_type": source_type,
                    "position": chunk.position, "content_checksum": chunk.checksum,
                    "document_checksum": checksum,
                }, created_at=now, updated_at=now,
            )
            self.repository.save(record)
            ids.append(record.id)
        try:
            vectors = self.embeddings.embed_documents([
                self.repository.get(item).searchable_text for item in ids
            ])
            records = [self.repository.get(item) for item in ids]
            self.vector_store.upsert([
                VectorRecord(record.id, vector, record.vector_payload())
                for record, vector in zip(records, vectors)
            ])
            for record in records:
                record.index_state = IndexState.INDEXED
                self.repository.save(record, "document_index_complete")
        except Exception:
            logger.exception("document_index_pending document_id=%s", document_id)
        return ids

    def remove_document(self, request: MemoryOperationRequest) -> MemoryOperationResult:
        document_id = request.filters.get("document_id")
        if not document_id:
            raise ValueError("REMOVE_DOCUMENT requires document_id.")
        records = self.repository.list(
            tenant_id=request.tenant_id, user_id=request.user_id,
            scopes=[MemoryScope.KNOWLEDGE_BASE], project_id=request.project_id,
            document_id=document_id,
        )
        for record in records:
            self.repository.mark_deleted(record)
        self.vector_store.delete([record.id for record in records])
        self.repository.delete_document(document_id, request.tenant_id, request.user_id)
        return MemoryOperationResult(
            request.operation_id, request.action, "success",
            evidence=[{"type": "document_deletion", "document_id": document_id,
                       "chunks_deleted": len(records)}],
        )

    def _export(self, request: MemoryOperationRequest) -> MemoryOperationResult:
        result = self._list(request)
        result.action = MemoryAction.EXPORT
        result.evidence.append({
            "type": "export", "format": "json",
            "data": json.dumps([asdict(item) for item in result.records], default=str),
        })
        return result

    def _authorised_record(self, request: MemoryOperationRequest) -> MemoryRecord:
        if not request.memory_id:
            raise ValueError(f"{request.action.value.upper()} requires memory_id.")
        record = self.repository.get(request.memory_id)
        if not record or record.tenant_id != request.tenant_id:
            raise PermissionError("Memory not found or not authorised.")
        if record.user_id is not None and record.user_id != request.user_id:
            raise PermissionError("Memory not found or not authorised.")
        if record.scope == MemoryScope.PROJECT and record.project_id != request.project_id:
            raise PermissionError("Memory not found or not authorised.")
        if record.scope == MemoryScope.SESSION and record.session_id != request.session_id:
            raise PermissionError("Memory not found or not authorised.")
        return record

    @staticmethod
    def _scopes(raw) -> List[MemoryScope]:
        if raw:
            return [item if isinstance(item, MemoryScope) else MemoryScope(item) for item in raw]
        return list(MemoryScope)
