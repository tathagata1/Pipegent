from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from memory.domain import (
    MemoryAction, MemoryCandidate, MemoryOperationRequest, MemoryScope, MemorySource,
    MemoryType,
)
from memory.documents import DocumentIngestionService


def build_memory_tools(
    service, *, tenant_id: str, user_id: Optional[str], session_id: str = "default",
    project_id: Optional[str] = None,
) -> Tuple[Dict[str, Callable[..., Any]], List[Dict[str, Any]]]:
    """Strict, allowlisted tool facade; no raw database or Qdrant filters."""
    def operation(action, **kwargs):
        result = service.execute(MemoryOperationRequest(
            operation_id=uuid.uuid4().hex, action=action, tenant_id=tenant_id,
            user_id=user_id, session_id=session_id, project_id=project_id, **kwargs,
        ))
        return result.to_dict()

    def remember_information(content, memory_type, scope, reason,
                             source_message_ids=None, valid_until=None):
        candidate = MemoryCandidate(
            content=content, proposed_type=MemoryType(memory_type),
            proposed_scope=MemoryScope(scope), source=MemorySource.USER_EXPLICIT,
            reason=reason, confidence=1.0, importance=0.8,
            source_message_ids=source_message_ids or [], valid_until=valid_until,
        )
        return operation(
            MemoryAction.CREATE, memory=candidate, explicit_user_request=True,
            idempotency_key=f"tool:create:{tenant_id}:{user_id}:{content.casefold()}",
        )

    def search_memory(query, top_k=8, scopes=None):
        return operation(
            MemoryAction.SEARCH, query=query, top_k=min(20, max(1, int(top_k))),
            filters={"scopes": scopes or [item.value for item in MemoryScope]},
        )

    def list_memories(scopes=None):
        return operation(MemoryAction.LIST, filters={"scopes": scopes or [
            item.value for item in MemoryScope
        ]})

    def forget_memory(memory_id):
        return operation(MemoryAction.DELETE, memory_id=memory_id)

    def update_memory(memory_id, content, memory_type, scope, reason):
        return operation(
            MemoryAction.UPDATE, memory_id=memory_id,
            memory=MemoryCandidate(
                content=content, proposed_type=MemoryType(memory_type),
                proposed_scope=MemoryScope(scope), source=MemorySource.USER_EXPLICIT,
                reason=reason, confidence=1.0, importance=0.8,
            ), explicit_user_request=True,
        )

    def remove_document(document_id):
        return operation(
            MemoryAction.REMOVE_DOCUMENT, filters={"document_id": document_id}
        )

    def ingest_document(path, metadata=None):
        return DocumentIngestionService(service).ingest(
            Path(path), tenant_id=tenant_id, user_id=user_id,
            project_id=project_id, metadata=metadata or {},
        )

    tools = {
        "remember_information": remember_information, "search_memory": search_memory,
        "list_memories": list_memories, "forget_memory": forget_memory,
        "update_memory": update_memory, "ingest_document": ingest_document,
        "remove_document": remove_document,
    }
    enum = lambda cls: [item.value for item in cls]
    specs = [
        {"name": "remember_information", "description": "Store explicit user memory.",
         "input_schema": {"type": "object", "properties": {
             "content": {"type": "string", "maxLength": 12000},
             "memory_type": {"type": "string", "enum": enum(MemoryType)},
             "scope": {"type": "string", "enum": enum(MemoryScope)},
             "reason": {"type": "string", "maxLength": 500},
             "source_message_ids": {"type": "array", "items": {"type": "string"}},
         }, "required": ["content", "memory_type", "scope", "reason"],
         "additionalProperties": False}},
        {"name": "search_memory", "description": "Search authorised memory and knowledge.",
         "input_schema": {"type": "object", "properties": {
             "query": {"type": "string", "maxLength": 4000},
             "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
             "scopes": {"type": "array", "items": {
                 "type": "string", "enum": enum(MemoryScope)}},
         }, "required": ["query"], "additionalProperties": False}},
        {"name": "list_memories", "description": "List authorised stored memories.",
         "input_schema": {"type": "object", "properties": {
             "scopes": {"type": "array", "items": {
                 "type": "string", "enum": enum(MemoryScope)}},
         }, "required": [], "additionalProperties": False}},
        {"name": "forget_memory", "description": "Delete one authorised memory.",
         "input_schema": {"type": "object", "properties": {
             "memory_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
         }, "required": ["memory_id"], "additionalProperties": False}},
        {"name": "update_memory", "description": "Correct and supersede a memory.",
         "input_schema": {"type": "object", "properties": {
             "memory_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
             "content": {"type": "string", "maxLength": 12000},
             "memory_type": {"type": "string", "enum": enum(MemoryType)},
             "scope": {"type": "string", "enum": enum(MemoryScope)},
             "reason": {"type": "string", "maxLength": 500},
         }, "required": ["memory_id", "content", "memory_type", "scope", "reason"],
         "additionalProperties": False}},
        {"name": "remove_document", "description": "Delete a document and all chunks.",
         "input_schema": {"type": "object", "properties": {
             "document_id": {"type": "string", "maxLength": 128},
         }, "required": ["document_id"], "additionalProperties": False}},
        {"name": "ingest_document",
         "description": "Ingest an authorised local text or Markdown document.",
         "input_schema": {"type": "object", "properties": {
             "path": {"type": "string", "maxLength": 4096},
             "metadata": {"type": "object"},
         }, "required": ["path"], "additionalProperties": False}},
    ]
    return tools, specs
