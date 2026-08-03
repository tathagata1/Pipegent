# Pipegent

Pipegent supports self-hosted long-term memory and knowledge-base RAG using canonical
SQLite persistence, local Sentence Transformers embeddings, and Qdrant.

Pipegent is an open-source, tool-first AI agent that routes every user request through explicit tools. The agent core stays minimal while real capabilities come from plugins that you can create, configure, and share. This repository bundles the runtime, a manifest-based plugin loader, and a handful of starter plugins (calculator, coin flip, date/time, dice rolling, jokes, and speech output).

## Getting Started

Create the local application configuration:

```powershell
Copy-Item config\example.config.ini config\config.ini
```

Add your OpenAI API key to `config/config.ini`, then install the dependencies, start the
local Qdrant service, and launch Pipegent:

```powershell
python -m pip install -r requirements.txt
docker compose up -d qdrant
python main.py
```

The first run downloads the local Sentence Transformers embedding model. Qdrant data persists
in its Docker volume between restarts. Use `exit` or `quit` to leave the Pipegent prompt.

## Features
- **Plugin-first design** – every capability lives in `plugins/<name>/function.py` and exposes its API via `manifest.json`.
- **Manifest-driven prompts** – the executor system prompt is generated from plugin manifests so the LLM always knows which tools exist and what their JSON schemas expect.
- **Stateful planning/execution** – a user-facing Planner owns clarification, a typed plan, validation, retry/re-planning, and the final response. A constrained Executor receives exactly one step at a time.
- **Resumable workflows** – plans, revisions, results, validation decisions, retries, and clarification history are atomically persisted under `data/workflows/`.
- **Structured logging** – every run writes a time-stamped file under `logs/`, while the console stays minimal (`You:`, `thinking...`, `Agent:`). Logs capture planner/executor interactions, plugin-loading diagnostics, and failure traces without cluttering the terminal.
- **Config-driven OpenAI clients** – `config/config.ini` contains the OpenAI credentials and planner/executor settings in one place.

## Repository Structure
```
.
|-- main.py                  # CLI entry point + logging bootstrap + REPL loop
|-- config/
|   |-- __init__.py          # Loads settings from config.ini
|   |-- example.config.ini   # Safe configuration template
|   `-- config.ini           # Local configuration and secrets (git-ignored)
|-- agents/
|   |-- planner.py           # Planner agent + workflow coordinator
|   |-- tool_executor.py     # Constrained one-step Executor Agent
|   `-- workflow_models.py   # Typed plans and inter-agent contracts
|-- prompts/
|   |-- planner_prompt.py    # Planner-only behavioural prompt
|   |-- executor_prompt.py   # Executor-only behavioural prompt
|   `-- system_prompt.py     # Injects plugin specs into executor prompt
|-- services/
|   |-- plugin_loader.py     # Loads/validates plugin callables
|   |-- plan_repository.py   # Atomic JSON workflow persistence
|   |-- result_validator.py  # Evidence-based result validation
|   `-- workflow_state_machine.py # Explicit transition table
|-- tests/
|   `-- test_workflow.py     # Deterministic mocked workflow tests
|-- plugins/
|   |-- core_plugins/        # First-party tools shipped with Pipegent
|   `-- user_plugins/        # Space for custom/community tools
|-- user_files/              # Drop user-provided docs/images/etc. (git-ignored)
|-- data/                    # Runtime data
|   `-- workflows/           # Persisted workflow state
|-- logs/                    # Structured execution logs (git-ignored)
`-- requirements.txt         # Python dependencies (OpenAI SDK + optional extras)
```

## Detailed Setup
1. **Clone the repo** (or download it) and install dependencies:
   ```bash
   git clone <repo-url>
   cd Pipegent
   python -m venv .venv
   .venv\Scripts\activate  # Windows
   pip install -r requirements.txt
   ```
2. **Configure credentials**:
   - Copy `config/example.config.ini` to `config/config.ini`, then set your OpenAI key and adjust the model settings if needed:
   ```bash
   copy config\example.config.ini config\config.ini
   ```
   ```ini
   [OPENAI]
   chatgpt_key = sk-...

   [PLANNER_LLM]
   model = gpt-4o-mini
   temperature = 1

   [EXECUTER_LLM]
   model = gpt-4o-mini
   temperature = 1

   [AGENT]
   max_steps = 5
   ```
3. **Run the agent**:
   ```bash
   python main.py
   ```
   Type messages at the `You:` prompt; `exit` or `quit` stops the loop.

## Coordinated Workflow

The explicit states are `RETRIEVING_MEMORY`, `VALIDATING_RETRIEVED_CONTEXT`,
`UNDERSTANDING_INTENT`, `AWAITING_CLARIFICATION`, `PLANNING`, `READY_TO_EXECUTE`,
`EXECUTING_STEP`, `VALIDATING_STEP`, `REPLANNING`, `COMPLETED`, `BLOCKED`, `FAILED`,
and `CANCELLED`.
The state machine rejects invalid transitions.

The Planner carries a bounded, de-duplicated slice of successful context across workflows in
the same session and retrieves relevant memory before asking focused clarification questions.
Intent analysis and plan creation happen in one model call. Once sufficiently clear, the
Planner persists a structured `ExecutionPlan` with the selected tool and explicit arguments,
then dispatches only its current step. The Executor receives an `ExecutorStepRequest`
with minimum relevant dependency results and returns an `ExecutorStepResult`
containing evidence, errors, and discovered facts. The Planner validates the
evidence independently, then completes, retries, re-plans, blocks, or fails the
step. Plans saved by older versions without a selected tool still use the legacy Executor
model-routing fallback. Stable per-step idempotency keys and persisted results prevent completed
invocations from being dispatched again during normal resume. API callers can
also pass a stable `request_id` to `PlannerAgent.handle_request()` to deduplicate
whole workflow submissions.

Run the deterministic tests with:

```bash
python -m unittest discover -s tests -v
```

## How Plugins Work
- Each plugin directory must include:
  - `function.py` - defines one or more helpers; only the function named in the manifest is exposed.
  - `manifest.json` - describes the tool.
- `manifest.json` schema:
  ```json
  {
    "name": "calculator",
    "description": "Perform arithmetic on two numbers.",
    "input_schema": {
      "type": "object",
      "properties": {
        "a": {"type": "number"},
        "b": {"type": "number"},
        "operation": {"type": "string", "enum": ["add", "subtract", "multiply", "divide"]}
      },
      "required": ["a", "b", "operation"]
    },
    "execution_function": "calculator"
  }
  ```
- During startup `pipegent.services.plugin_loader.load_plugins()` validates each manifest (type checks, required keys, object schemas) and imports the specified function from `function.py`. Invalid plugins are skipped with a console warning.
- The resulting manifest data feeds `pipegent.prompts.system_prompt.build_system_prompt()`, which injects every tool description + JSON schema into the executor system prompt.

## Bundled Core Plugins
Pipegent now ships with a broad starter suite so most automation tasks can be handled without writing new tools:
- **Filesystem helpers** – `file_manager` safely copies/moves/deletes files inside the repo, while `archive_manager` zips or unzips directories with path-traversal protection.
- **Data fetchers** – `web_scraper`, `http_post_json`, `rss_reader`, `github_repo_fetcher`, and `email_sender` cover general HTTP GET/POST flows, feed parsing, GitHub API access, and SMTP delivery (credentials never echoed back into responses).
- **Local integrations** – `sqlite_query` executes parameterized SQL, `table_parser` reads CSV/XLSX (requires `openpyxl`), `xlsx_writer` outputs structured workbooks, `xls_reader` handles legacy Excel files, `docx_reader`/`docx_writer` manage Word docs, and `pptx_reader`/`pptx_writer` cover slide decks (via `python-docx`/`python-pptx`).
- **Text + utility set** – Calculator, dice/coin, speech, and string casing plugins continue to exist so legacy prompts remain compatible.

> Optional dependencies: install `openpyxl`, `xlrd`, `python-docx`, `python-pptx`, `pillow`, and `pytesseract` (plus the native Tesseract binary) to unlock spreadsheet/Office/OCR tooling.

## Logging & Telemetry

Every run prints the path to a new `logs/pipegent_<timestamp>.log`. The default `DEBUG`
trace includes:

- model call IDs, purpose, model, full request messages, raw responses, finish reasons,
  token usage, latency, and errors;
- observable planner decisions (intent, assumptions, plans, re-plans, validation, and final
  answer construction) plus every workflow state transition;
- selected tools, redacted arguments, outputs, duration, timeouts, retries, and failures;
- memory requests, retrieved context, policy decisions, results, and indexing failures; and
- plugin discovery and the generated executor system-prompt size.

Events are emitted as single-line JSON after the timestamp/logger prefix, making the file
readable with a text editor and searchable by event name (for example `llm.request`,
`tool.result`, or `workflow.transition`). Known credential fields such as API keys,
authorization headers, passwords, and access tokens are replaced with `[REDACTED]`.

The trace contains user prompts, retrieved memories, and tool data, so treat log files as
sensitive. It records all reasoning artifacts Pipegent can observe, but model APIs do not
expose private chain-of-thought. Plans, decisions, tool selections, and final outputs are the
available explanation of model behaviour.

Logging can be tuned with:

- `PIPEGENT_LOG_LEVEL` (`DEBUG` by default; use `INFO` for summaries only);
- `PIPEGENT_LOG_TO_CONSOLE` (`false` by default);
- `PIPEGENT_LOG_MAX_VALUE_CHARS` (`50000`; `0` disables per-value truncation);
- `PIPEGENT_LOG_MAX_BYTES` (`10485760`; `0` disables rotation); and
- `PIPEGENT_LOG_BACKUP_COUNT` (`3`).

The console stays minimal (`You:`, `thinking...`, `Agent:`). If an older model response returns
structured final JSON, its `message`, `final_answer`, or `final_message` value is displayed; the
complete payload remains available in the verbose log and persisted workflow.

For GPT-5-family models, orchestration defaults to `minimal` reasoning effort and `low`
verbosity. Override these with `PIPEGENT_REASONING_EFFORT` and
`PIPEGENT_RESPONSE_VERBOSITY`. Final tool results are formatted locally by default, avoiding a
separate response-synthesis model call; set `PIPEGENT_SYNTHESIZE_FINAL_RESPONSE=true` if a more
polished model-written final answer is worth the added latency. The local embedding model warms
in a background thread so the prompt becomes available without waiting for model startup.

## Working with User Files
- Place any documents/spreadsheets/images you want the agent to read under `user_files/` at the repo root. The automation tools automatically look there even if you mention an external OS path like `C:\Users\me\Downloads\foo.docx`.
- Outputs you plan to keep long-term can be written anywhere, but for inputs, keeping them in `user_files/` avoids permission issues and keeps everything under version control (the directory is ignored by git by default).

## Adding a New Plugin
1. Create a folder under `plugins/`, e.g. `plugins/weather/`.
2. Add `function.py` with the callable you want to expose:
   ```python
   import requests

   def get_weather(city: str) -> str:
       ...
   ```
3. Add `manifest.json` describing the tool (see schema above) and set `"execution_function": "get_weather"`.
4. Optionally add dependency installation/build steps to the README or a dedicated requirements file.
5. Restart `python main.py` so the loader picks up the new plugin. If the manifest is invalid, the console will show a validation error.

## Long-Term Memory and Knowledge-Base RAG

### Architecture

Pipegent retains its existing Planner-to-Executor workflow and JSON workflow repository.
Memory is a separate subsystem:

`Planner -> MemoryOperationRequest -> Executor -> MemoryService`

`MemoryService` applies deterministic policy, writes canonical SQLite data, embeds text, and
indexes it through the replaceable `VectorStore` interface. `MemoryRetriever` performs
metadata-filtered semantic search, loads canonical records, rejects inactive, expired, or
out-of-scope records, and ranks results using configurable semantic, importance, confidence,
recency, and lexical scores. `RetrievalContextBuilder` produces bounded reference context for
the Planner.

Canonical and vector storage are separate because the vector index is replaceable and can be
rebuilt. SQLite preserves canonical text, ownership, provenance, revisions, operations, user
settings, document metadata, audit events, validity, supersession links, and indexing state.
If embedding or Qdrant fails, the canonical record remains in a recoverable `pending` state
for reindexing.

The primary abstraction boundaries are `EmbeddingProvider`, `VectorStore`, and
`MemoryRepository`. This allows Qdrant or Sentence Transformers to be replaced by pgvector,
Chroma, FAISS, another local model, a remote embedding service, or another relational store
without changing the agent layer.

### Embeddings and Qdrant

The default embedding model is `sentence-transformers/all-MiniLM-L6-v2`:

- 384 vector dimensions
- Normalized embeddings
- Cosine distance
- CPU execution by default

The Qdrant collection defaults to `agent_memory_v1`. Vector payloads contain the memory ID,
tenant, user, agent, session and project ownership, scope, type, source, status, tags,
sensitivity, creation time, and validity dates. Every search includes tenant filtering and
the applicable user, session, project, and agent filters.

The local stack pins Qdrant Server `1.15.1` and `qdrant-client` `1.16.2`; their minor-version
difference is within Qdrant's supported compatibility range.

Memory scopes are `user`, `session`, `project`, `agent`, `organisation`, and
`knowledge_base`. Memory types include user facts and preferences, project facts, decisions,
task outcomes, procedures, observations, corrections, and document chunks. Imported document
chunks always use the knowledge-base scope and imported-document source, keeping them
separate from interaction memory.

### Memory Workflows and User Controls

Explicit `remember`, `save`, or `learn` requests become structured Executor operations. The
policy rejects secret-like content, canonical storage runs first, and success is confirmed
only after persistence evidence is returned. Exact duplicates reuse the existing record.
Corrections create linked revisions and supersede the previous fact instead of erasing audit
history. Temporary constraints use validity dates and session or project scope.

Automatic storage is disabled by default. Agent-proposed candidates remain source-classified;
low-confidence, inferred, or sensitive information is ignored or requires confirmation.
Passwords, API keys, access tokens, cookies, authentication headers, private keys, one-time
passwords, security codes, hidden prompts, and private reasoning are rejected.

Relevant memories are retrieved before planning. Retrieved text is delimited as untrusted
reference data: it cannot override the current user message, provide system instructions, or
cause commands to execute. Ownership, status, scope, validity, and freshness are checked
against canonical records.

Memory operations support listing, searching, correcting, deleting, exporting, reindexing,
and consolidation. Users can disable automatic storage, disable retrieval, disable all memory,
or disable memory for the current conversation. Removing an ingested document marks its
canonical chunks deleted, removes their vectors, deletes the document registry entry, and
records audit events.

### Memory Setup

Install dependencies and start Qdrant:

```powershell
python -m pip install -r requirements.txt
docker compose up -d qdrant
Copy-Item .env.example .env
python main.py
```

Pipegent loads Sentence Transformers during startup from its normal local cache so model
initialisation cannot stall the first user request. To prefetch the model once:

```powershell
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"
```

Memory configuration is environment based:

- `MEMORY_ENABLED`, default `true`
- `MEMORY_AUTO_STORE_ENABLED`, default `false`
- `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION_PREFIX`
- `EMBEDDING_MODEL`, `EMBEDDING_DEVICE`, `EMBEDDING_BATCH_SIZE`
- `EMBEDDING_LOCAL_FILES_ONLY`, default `true`; set it to `false` only while downloading
  a model that is not already cached
- `MEMORY_DEFAULT_TOP_K`, `MEMORY_MAX_CONTEXT_ITEMS`, `MEMORY_MIN_SIMILARITY`
- `MEMORY_AUTO_STORE_CONFIDENCE`, `MEMORY_AUTO_STORE_IMPORTANCE`

Do not commit credentials. Canonical memory is stored at `data/memory.sqlite3`; Qdrant stores
its index in the Docker volume declared by `docker-compose.yml`. Organisation-wide scope
should only be enabled after connecting the deployment's identity and role provider.

### Memory Testing and Evaluation

```powershell
python -m pytest -q
python evaluation/evaluate_memory.py
```

Unit tests use deterministic local embeddings and an in-memory vector store. Qdrant
integration tests require the Compose service and are enabled with:

```powershell
$env:RUN_QDRANT_INTEGRATION = "1"
python -m pytest tests/test_qdrant_integration.py -q
```

The evaluation dataset reports precision at K, recall at K, mean reciprocal rank,
tenant-isolation failures, expired-memory retrieval failures, and conflict-resolution
failures.

Current limitations:

- Lexical ranking is performed in process rather than through SQLite FTS.
- Organisation authorization needs the host product's identity and role provider.
- Automatic candidate-extraction prompts are available, but automatic storage remains
  intentionally disabled by default.
- Memory telemetry currently uses structured logs rather than a Prometheus exporter.
