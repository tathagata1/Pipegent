import importlib.util
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

class ManifestValidationError(ValueError):
    pass


def _validate_input_schema(schema: Any) -> Dict[str, Any]:
    if schema is None:
        return {"type": "object", "properties": {}, "required": []}
    if not isinstance(schema, dict):
        raise ManifestValidationError("input_schema must be a JSON object")

    schema_type = schema.get("type", "object")
    if schema_type != "object":
        raise ManifestValidationError("input_schema.type must be 'object'")

    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise ManifestValidationError("input_schema.properties must be an object")

    required = schema.get("required", [])
    if required is None:
        required = []
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise ManifestValidationError("input_schema.required must be an array of strings")

    normalized = dict(schema)
    normalized["type"] = "object"
    normalized["properties"] = properties
    normalized["required"] = required
    return normalized


def _validate_manifest(manifest: Any) -> Dict[str, Any]:
    if not isinstance(manifest, dict):
        raise ManifestValidationError("Manifest root must be a JSON object")

    name = manifest.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ManifestValidationError("'name' must be a non-empty string")

    description = manifest.get("description", "No description provided.")
    if not isinstance(description, str):
        raise ManifestValidationError("'description' must be a string")

    function_name = manifest.get("execution_function")
    if not isinstance(function_name, str) or not function_name.strip():
        raise ManifestValidationError("'execution_function' must be a non-empty string")

    input_schema = _validate_input_schema(manifest.get("input_schema"))

    return {
        "name": name.strip(),
        "description": description.strip(),
        "execution_function": function_name.strip(),
        "input_schema": input_schema,
    }


def load_plugins(plugins_dir: Path) -> Tuple[Dict[str, Callable], List[Dict[str, Any]]]:
    tools: Dict[str, Callable] = {}
    manifests: List[Dict[str, Any]] = []

    if not plugins_dir.exists():
        return tools, manifests

    for plugin_dir in sorted(p for p in plugins_dir.iterdir() if p.is_dir()):
        module_path = plugin_dir / "function.py"
        manifest_path = plugin_dir / "manifest.json"
        if not module_path.exists() or not manifest_path.exists():
            print(f"Plugin '{plugin_dir.name}' skipped: missing function.py or manifest.json")
            continue

        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = _validate_manifest(manifest_data)
        except (json.JSONDecodeError, ManifestValidationError) as exc:
            print(f"Plugin '{plugin_dir.name}' skipped: {exc}")
            continue

        spec = importlib.util.spec_from_file_location(
            f"plugins.{plugin_dir.name}.function", module_path
        )
        if spec is None or spec.loader is None:
            print(f"Plugin '{plugin_dir.name}' skipped: could not create import spec")
            continue

        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)  # type: ignore[call-arg]
        except Exception as exc:
            print(f"Plugin '{plugin_dir.name}' skipped: failed to load module ({exc})")
            continue

        func = getattr(module, manifest["execution_function"], None)
        if not callable(func):
            print(
                f"Plugin '{plugin_dir.name}' skipped: execution function '{manifest['execution_function']}' is invalid"
            )
            continue

        if manifest["name"] in tools:
            print(f"Duplicate plugin name '{manifest['name']}' detected; skipping '{plugin_dir.name}'")
            continue

        tools[manifest["name"]] = func
        manifests.append(
            {
                "name": manifest["name"],
                "description": manifest["description"],
                "input_schema": manifest["input_schema"],
            }
        )

    return tools, manifests
