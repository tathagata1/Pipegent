# Pipegent

Pipegent is an open-source, tool-first AI agent that routes every user request through explicit tools. The agent core stays minimal while the real capabilities come from plugins that you can create, configure, and share. This repository contains the runtime, a manifest-based plugin loader, and a handful of starter plugins (calculator, coin flip, date/time, dice rolling, jokes, and speech output).

## Features
- **Plugin-first design** – each capability lives in `plugins/<name>/function.py` and declares its interface via `manifest.json`.
- **Strict tool orchestration** – the agent’s system prompt enumerates all manifest metadata so the LLM always knows which tools exist and what args they accept.
- **Safety checks** – the plugin manager validates manifest schemas before loading code, and skips misconfigured plugins instead of crashing the agent.
- **Persistent conversation state** – chat history stays in memory for the lifetime of the process so the model retains context between turns.
- **Config-driven OpenAI client** – API keys, model name, and temperature are pulled from `config.ini` through `config.py`.

## Repository Structure
```
??? agent.py              # Agent class that manages history, tool calls, and final responses
??? main.py               # Entry point that wires config + plugins into the agent loop
??? plugin_manager.py     # Loads/validates plugins and returns callables + manifest specs
??? prompt_builder.py     # Renders the system prompt from plugin metadata
??? config.py / config.ini# Configuration helpers and secrets (API keys, model, temperature)
??? requirements.txt      # Python dependencies (currently the OpenAI SDK)
??? plugins/
    ??? <plugin_name>/
        ??? function.py   # Python file that defines the callable exported in the manifest
        ??? manifest.json # Metadata describing the tool (name, description, input schema)
```

## Setup
1. **Clone the repo** (or download it) and install dependencies:
   ```bash
   git clone <repo-url>
   cd Pipegent
   python -m venv .venv
   .venv\Scripts\activate  # Windows
   pip install -r requirements.txt  # add packages as needed (openai, etc.)
   ```
2. **Configure credentials** by copying `example.copy.ini` to `config.ini` (or editing the existing file) and setting your OpenAI key + agent defaults:
   ```ini
   [OPENAI]
   chatgpt_key = sk-...

   [AGENT]
   model = gpt-4o-mini
   temperature = 0.0
   ```
3. **Run the agent**:
   ```bash
   python main.py
   ```
   Type messages at the `You:` prompt; `exit` or `quit` stops the loop.

## How Plugins Work
- Each plugin directory must include:
  - `function.py` – defines one or more helpers; only the function named in the manifest is exposed.
  - `manifest.json` – describes the tool.
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
- During startup `plugin_manager.load_plugins()` validates each manifest (type checks, required keys, object schemas) and imports the specified function from `function.py`. Invalid plugins are skipped with a console warning.
- The resulting manifest data feeds `prompt_builder.build_system_prompt()`, which injects every tool’s description + JSON schema into the agent’s system prompt. This guarantees the LLM knows the argument contract for every tool.

## Adding a New Plugin
1. Create a folder under `plugins/`, e.g. `plugins/weather/`.
2. Add `function.py` with the callable you want to expose:
   ```python
   import requests

   def get_weather(city: str) -> str:
       ...
   ```
3. Add `manifest.json` describing the tool (see schema above) and set `"execution_function": "get_weather"`.
4. Optionally add dependency installation/build steps to the README or a requirements file.
5. Restart `python main.py` so the loader picks up the new plugin. If the manifest is invalid, the console will show a validation error.