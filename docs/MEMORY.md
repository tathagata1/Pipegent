# Long-term memory and knowledge-base RAG

## Architecture

Pipegent retains its existing Planner → one-step Executor workflow and JSON workflow
repository. Memory is a separate subsystem:

`Planner → structured MemoryOperationRequest → Executor → MemoryService`

`MemoryService` applies deterministic policy, writes canonical SQLite data, embeds text,
and indexes it through the `VectorStore` protocol. `MemoryRetriever` performs
metadata-filtered semantic search, loads canonical records, rejects inactive/expired or
out-of-scope records, applies configurable semantic/importance/confidence/recency/lexical
scoring, and gives bounded results to `RetrievalContextBuilder`.

Canonical and vector storage are separate because an embedding index is replaceable and can
be rebuilt. SQLite preserves text, ownership, provenance, revisions, operations, settings,
document metadata, audit events, validity, supersession links, and indexing state. If
embedding or Qdrant fails, the record remains `pending` and `REINDEX` can reconcile it.

The abstraction boundaries are `EmbeddingProvider`, `VectorStore`, and
`MemoryRepository`. A pgvector, Chroma, FAISS, remote embedding, or alternative relational
adapter can replace one layer without changing agents.

## Model and collection

The default model is `sentence-transformers/all-MiniLM-L6-v2`: 384 dimensions, normalized
vectors, cosine distance. The Qdrant collection defaults to `agent_memory_v1`. Payloads
contain the memory ID, tenant/user/agent/session/project ownership, scope, type, source,
status, tags, sensitivity, creation time, and validity dates. Every search includes a tenant
filter plus user/session/project filters as applicable.

Memory scopes are `user`, `session`, `project`, `agent`, `organisation`, and
`knowledge_base`. Types are user fact/preference, project fact, decision, task outcome,
procedure, observation, correction, and document chunk. Imported chunks always use the
knowledge-base scope and imported-document source; they are not mixed with interaction
memory.

## Workflows and controls

Explicit “remember/save/learn” requests become Executor memory operations. The policy rejects
secret-like content, canonical storage runs first, and success is confirmed only after
canonical and vector evidence. Exact duplicates return the existing record. Corrections
create a revision-linked record and supersede, rather than erase, the previous fact.
Temporary constraints use validity dates and a session/project scope.

Automatic storage is disabled by default. Agent candidates remain source-classified;
low-confidence, inferred, or sensitive candidates are ignored or require confirmation.
Passwords, keys, tokens, cookies, authentication headers, private keys, OTPs, security codes,
hidden prompts, and private reasoning are rejected.

Before planning, relevant memory can be retrieved. Retrieved text is clearly delimited as
untrusted reference data. It cannot override the current message or supply executable
instructions. Status, ownership, validity, and freshness are checked against canonical data.

Users can list/search, correct, delete, export, disable automatic storage, disable retrieval,
or disable all memory through structured operations/settings. Document removal marks every
canonical chunk deleted, removes vectors, deletes its document registry entry, and writes
audit events. Consolidation supersedes exact duplicates without permanent deletion.

## Local setup

```powershell
python -m pip install -r requirements.txt
docker compose up -d qdrant
Copy-Item .env.example .env
python main.py
```

Sentence Transformers downloads the model on first use into its normal local model cache,
then reuses the loaded process-wide provider. It is not initialized per request. To prefetch:

```powershell
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"
```

Configuration is environment based:

- `MEMORY_ENABLED`, default `true`
- `MEMORY_AUTO_STORE_ENABLED`, default `false`
- `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION_PREFIX`
- `EMBEDDING_MODEL`, `EMBEDDING_DEVICE`, `EMBEDDING_BATCH_SIZE`
- `MEMORY_DEFAULT_TOP_K`, `MEMORY_MAX_CONTEXT_ITEMS`, `MEMORY_MIN_SIMILARITY`
- `MEMORY_AUTO_STORE_CONFIDENCE`, `MEMORY_AUTO_STORE_IMPORTANCE`

Do not commit API keys. SQLite is stored at `data/memory.sqlite3`; Qdrant uses its Docker
volume. Apply organisation authorization before enabling organisation scope in a multi-user
deployment.

## Testing and evaluation

```powershell
python -m pytest -q
python evaluation/evaluate_memory.py
```

Unit tests use deterministic local embeddings and an in-memory vector store. Qdrant tests are
opt-in with `RUN_QDRANT_INTEGRATION=1` and require the Compose service. The evaluation dataset
reports precision@K, recall@K, MRR, tenant-isolation failures, expired-result failures, and
conflict failures.

Current limitations: lexical search is an in-process reranking feature rather than SQLite
FTS; organisation authorization is represented by scope filters but needs the product’s
future identity/role provider; automatic candidate extraction prompts are supplied but
automatic storage remains intentionally disabled; metrics are structured log events rather
than a Prometheus exporter.
