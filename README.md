# Pipegent

Pipegent is an open-source, tool-first AI agent that routes every user request through explicit tools. The agent core stays minimal while real capabilities come from plugins that you can create, configure, and share. This repository bundles the runtime, a manifest-based plugin loader, and a handful of starter plugins (calculator, coin flip, date/time, dice rolling, jokes, and speech output).

## Features
- **Plugin-first design** - each capability lives in `plugins/<name>/function.py` and exposes its API via `manifest.json`.
- **Manifest-driven prompts** - the executor system prompt is generated from plugin manifests so the LLM always knows which tools exist and what their JSON schemas expect.
- **Two-tier planning/execution** - a planner LLM decomposes requests into bounded steps and a dedicated executor LLM completes each step with the available tools, honoring `AGENT.max_steps` to avoid infinite loops.
- **Ephemeral tempstore** - step outputs are written to `tempstore/` with random alphanumeric filenames and deleted automatically when execution finishes.
- **Config-driven OpenAI clients** - `system.config.ini` holds shared defaults while `user.config.ini` keeps developer-specific secrets such as API keys.

## Repository Structure
```
.
|-- main.py                  # CLI entry point that wires config + plugins into the workflow
|-- config.py                # Configuration helper that merges system + user config layers
|-- system.config.ini        # Repository defaults (models, temps, max steps)
|-- user.config.ini          # Developer secrets and overrides (OpenAI key, etc.)
|-- pipegent/                # Package with agents, prompts, and services
|   |-- agents/
|   |   |-- planner.py       # Planner agent orchestration logic
|   |   `-- tool_executor.py # Executor that routes to plugins
|   |-- prompts/
|   |   `-- system_prompt.py # Builds executor system prompt from plugin specs
|   `-- services/
|       `-- plugin_loader.py # Loads/validates plugins and returns callables + manifest specs
|-- requirements.txt         # Python dependencies (currently just the OpenAI SDK)
`-- plugins/
    `-- <plugin_name>/
        |-- function.py
        `-- manifest.json
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
New capability-oriented plugins extend the baseline toolkit beyond text transforms:
- **Filesystem helpers**: `file_manager` safely copies/moves/deletes files inside the repo, while `archive_manager` zips or unzips directories without path traversal risks.
- **Data fetchers**: `web_scraper`, `http_post_json`, `rss_reader`, `github_repo_fetcher`, and `email_sender` cover general HTTP GET/POST flows, feed parsing, GitHub API access, and SMTP delivery (credentials never echoed back).
- **Local integrations**: `sqlite_query` executes parameterized SQL, `table_parser` reads CSV/XLSX (requires `openpyxl` for spreadsheets), and `image_ocr` pipes images through Tesseract via `pytesseract`/Pillow.
- **Utility set**: The earlier calculator, string transforms, dice/coin, etc., remain available so legacy prompts keep working.

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
