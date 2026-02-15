# Pipegent

Pipegent is an open-source, tool-first AI agent that routes every user request through explicit tools. The agent core stays minimal while real capabilities come from plugins that you can create, configure, and share. This repository bundles the runtime, a manifest-based plugin loader, and a handful of starter plugins (calculator, coin flip, date/time, dice rolling, jokes, and speech output).

> **Before you run Pipegent:** install all dependencies with `pip install -r requirements.txt`.

## Features
- **Plugin-first design** – every capability lives in `plugins/<name>/function.py` and exposes its API via `manifest.json`.
- **Manifest-driven prompts** – the executor system prompt is generated from plugin manifests so the LLM always knows which tools exist and what their JSON schemas expect.
- **Two-tier planning/execution** – a planner LLM decomposes requests into bounded steps and a dedicated executor LLM completes each step with the available tools, honoring `AGENT.max_steps` to avoid infinite loops.
- **Ephemeral tempstore** – step outputs are written to `tempstore/` with random alphanumeric filenames and deleted automatically when execution finishes.
- **Structured logging** – every run writes a time-stamped file under `logs/`, while the console stays minimal (`You:`, `thinking...`, `Agent:`). Logs capture planner/executor interactions, plugin-loading diagnostics, and failure traces without cluttering the terminal.
- **Config-driven OpenAI clients** – `system.config.ini` holds shared defaults while `user.config.ini` keeps developer-specific secrets such as API keys.

## Repository Structure
```
.
|-- main.py                  # CLI entry point + logging bootstrap + REPL loop
|-- config.py                # Configuration helper that merges system + user config layers
|-- system.config.ini        # Repository defaults (models, temps, max steps)
|-- user.config.ini          # Developer secrets and overrides (OpenAI key, etc.)
|-- agents/
|   |-- planner.py           # Planner agent orchestration logic (+context persistence)
|   `-- tool_executor.py     # Executor that routes to plugins
|-- prompts/
|   `-- system_prompt.py     # Builds executor system prompt from plugin specs
|-- services/
|   `-- plugin_loader.py     # Loads/validates plugins and returns callables + manifest specs
|-- plugins/
|   |-- core_plugins/        # First-party tools shipped with Pipegent
|   `-- user_plugins/        # Space for custom/community tools
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
   - Copy `example.copy.ini` to `system.config.ini` if you need a fresh baseline (or edit the existing file) to define default planner/executor settings.
   - Create `user.config.ini` (git-ignored) for secrets and overrides, then set your OpenAI key plus any personal tweaks:
   ```ini
   [OPENAI]
   chatgpt_key = sk-...

   [PLANNER_LLM]
   model = gpt-4o-mini
   temperature = 0.2

   [EXECUTER_LLM]
   model = gpt-4o-mini
   temperature = 0.0

   [AGENT]
   max_steps = 5
   ```
3. **Run the agent**:
   ```bash
   python main.py
   ```
   Type messages at the `You:` prompt; `exit` or `quit` stops the loop.

## Complex Request Execution
1. The planner LLM receives the raw user request, the list of available tools, and `max_steps`. It returns a JSON plan containing at most `max_steps` ordered steps.
2. For each step, the planner builds an instruction for the executor LLM. The executor must respond with tool-call JSON (calculator, get_time, etc.). Tool outputs are stored in `tempstore/<random>.txt` for the duration of the run, allowing subsequent steps to reference previous results.
3. After all steps finish, the planner summarizes the collected outputs and responds to the user. Temporary files are removed automatically so `tempstore/` never retains stale data.

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
