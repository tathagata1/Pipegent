# Pipegent

Pipegent supports self-hosted long-term memory and knowledge-base RAG using canonical
SQLite persistence, local Sentence Transformers embeddings, and Qdrant. See
[docs/MEMORY.md](docs/MEMORY.md) for architecture, privacy controls, setup, testing, and
reindexing guidance.

Pipegent is an open-source, tool-first AI agent that routes every user request through explicit tools. The agent core stays minimal while real capabilities come from plugins that you can create, configure, and share. This repository bundles the runtime, a manifest-based plugin loader, and a handful of starter plugins (calculator, coin flip, date/time, dice rolling, jokes, and speech output).

> **Before you run Pipegent:** install all dependencies with `pip install -r requirements.txt`.

## Features
- **Plugin-first design** – every capability lives in `plugins/<name>/function.py` and exposes its API via `manifest.json`.
- **Manifest-driven prompts** – the executor system prompt is generated from plugin manifests so the LLM always knows which tools exist and what their JSON schemas expect.
- **Stateful planning/execution** – a user-facing Planner owns clarification, a typed plan, validation, retry/re-planning, and the final response. A constrained Executor receives exactly one step at a time.
- **Resumable workflows** – plans, revisions, results, validation decisions, retries, and clarification history are atomically persisted under `data/workflows/`.
- **Ephemeral tempstore** – step outputs are written to `tempstore/` with random alphanumeric filenames and deleted automatically when execution finishes.
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
|-- tempstore/               # Ephemeral files (auto-cleaned per run)
|-- logs/                    # Structured execution logs (git-ignored)
`-- requirements.txt         # Python dependencies (OpenAI SDK + optional extras)
```

## Setup
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

The explicit states are `UNDERSTANDING_INTENT`, `AWAITING_CLARIFICATION`,
`PLANNING`, `READY_TO_EXECUTE`, `EXECUTING_STEP`, `VALIDATING_STEP`,
`REPLANNING`, `COMPLETED`, `BLOCKED`, `FAILED`, and `CANCELLED`.
The state machine rejects invalid transitions.

The Planner checks prior conversation context before asking focused clarification
questions. Once sufficiently clear, it persists a structured `ExecutionPlan` and
dispatches only its current step. The Executor receives an `ExecutorStepRequest`
with minimum relevant dependency results and returns an `ExecutorStepResult`
containing evidence, errors, and discovered facts. The Planner validates the
evidence independently, then completes, retries, re-plans, blocks, or fails the
step. Stable per-step idempotency keys and persisted results prevent completed
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
- Every run generates `logs/pipegent_<timestamp>.log` with INFO-level summaries and DEBUG traces of planner/executor/tool activity. Console output stays minimal (`You:`, `thinking...`, `Agent:`) to emphasize the user dialogue.
- `tempstore/` continues to hold intermediate artifacts across steps; filenames are referenced inside logs for easier troubleshooting.

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
