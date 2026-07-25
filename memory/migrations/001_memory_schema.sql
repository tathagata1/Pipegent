-- Reference migration. MemoryRepository performs equivalent idempotent startup migration.
CREATE TABLE IF NOT EXISTS memories (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT, agent_id TEXT,
  session_id TEXT, project_id TEXT, scope TEXT NOT NULL, memory_type TEXT NOT NULL,
  source TEXT NOT NULL, status TEXT NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL,
  searchable_text TEXT NOT NULL, confidence REAL NOT NULL, importance REAL NOT NULL,
  sensitivity TEXT NOT NULL, requires_confirmation INTEGER NOT NULL,
  tags_json TEXT NOT NULL, entities_json TEXT NOT NULL, source_message_ids_json TEXT NOT NULL,
  source_document_id TEXT, source_chunk_id TEXT, valid_from TEXT, valid_until TEXT,
  last_accessed_at TEXT, access_count INTEGER NOT NULL DEFAULT 0,
  supersedes_memory_id TEXT, superseded_by_memory_id TEXT, embedding_model TEXT,
  embedding_version TEXT, index_state TEXT NOT NULL, metadata_json TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
