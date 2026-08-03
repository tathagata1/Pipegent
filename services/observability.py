"""Structured, redacted diagnostics for model and tool activity.

The log records everything the application can actually observe: prompts, model
outputs, plans, tool calls, state changes, token usage, timings, and exceptions.
Model providers do not expose private chain-of-thought, so it cannot be logged.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, Mapping


_REDACTED = "[REDACTED]"
_SENSITIVE_KEYS = {
    "api_key", "apikey", "authorization", "chatgpt_key", "cookie",
    "openai_api_key", "password", "passwd", "refresh_token", "secret",
    "secret_key", "access_token",
}


def _max_value_chars() -> int:
    try:
        return max(0, int(os.getenv("PIPEGENT_LOG_MAX_VALUE_CHARS", "50000")))
    except ValueError:
        return 50000


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).strip().casefold().replace("-", "_")
    return (
        normalized in _SENSITIVE_KEYS
        or normalized.endswith("_api_key")
        or normalized.endswith("_password")
        or normalized.endswith("_secret")
        or normalized.endswith("_access_token")
        or normalized.endswith("_refresh_token")
    )


def safe_for_log(value: Any, *, _seen: set[int] | None = None) -> Any:
    """Convert arbitrary values into bounded JSON data and redact secret fields."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        limit = _max_value_chars()
        if limit and len(value) > limit:
            return value[:limit] + f"...[truncated {len(value) - limit} characters]"
        return value
    if isinstance(value, bytes):
        return f"<bytes length={len(value)}>"
    if isinstance(value, (Path, Enum)):
        return str(value.value if isinstance(value, Enum) else value)

    seen = _seen if _seen is not None else set()
    identity = id(value)
    if identity in seen:
        return "<recursive reference>"
    seen.add(identity)
    try:
        if is_dataclass(value) and not isinstance(value, type):
            return safe_for_log(asdict(value), _seen=seen)
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            return safe_for_log(model_dump(), _seen=seen)
        if isinstance(value, Mapping):
            return {
                str(key): _REDACTED if _is_sensitive_key(key)
                else safe_for_log(item, _seen=seen)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple, set, frozenset)):
            return [safe_for_log(item, _seen=seen) for item in value]
        return safe_for_log(str(value), _seen=seen)
    finally:
        seen.discard(identity)


def log_event(
    target: logging.Logger, event: str, *, level: int = logging.DEBUG, **fields: Any,
) -> None:
    """Write one searchable JSON event through the normal Python logger."""
    if not target.isEnabledFor(level):
        return
    payload = {"event": event, **fields}
    try:
        rendered = json.dumps(
            safe_for_log(payload), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        )
    except Exception as exc:
        # Diagnostics must never make an otherwise valid agent operation fail.
        rendered = json.dumps({
            "event": event,
            "logging_serialization_error": f"{type(exc).__name__}: {exc}",
        }, ensure_ascii=False, separators=(",", ":"))
    target.log(level, rendered)


def _response_details(response: Any) -> Dict[str, Any]:
    choices = []
    for choice in getattr(response, "choices", []) or []:
        message = getattr(choice, "message", None)
        choices.append({
            "index": getattr(choice, "index", None),
            "finish_reason": getattr(choice, "finish_reason", None),
            "message": {
                "role": getattr(message, "role", None),
                "content": getattr(message, "content", None),
                "refusal": getattr(message, "refusal", None),
                "tool_calls": getattr(message, "tool_calls", None),
            } if message is not None else None,
        })
    return {
        "response_id": getattr(response, "id", None),
        "created": getattr(response, "created", None),
        "model": getattr(response, "model", None),
        "usage": getattr(response, "usage", None),
        "choices": choices,
    }


def logged_chat_completion(
    *, client: Any, target: logging.Logger, component: str, purpose: str,
    model: str, messages: list[dict[str, Any]], context: Dict[str, Any] | None = None,
    **request_options: Any,
) -> Any:
    """Call Chat Completions and emit detailed request/response trace events."""
    call_id = uuid.uuid4().hex
    trace_context = context or {}
    log_event(
        target, "llm.request", call_id=call_id, component=component,
        purpose=purpose, model=model, messages=messages,
        request_options=request_options, **trace_context,
    )
    started = perf_counter()
    try:
        response = client.chat.completions.create(
            model=model, messages=messages, **request_options
        )
    except Exception as exc:
        elapsed_ms = round((perf_counter() - started) * 1000, 2)
        log_event(
            target, "llm.error", level=logging.ERROR, call_id=call_id,
            component=component, purpose=purpose, model=model,
            elapsed_ms=elapsed_ms, error_type=type(exc).__name__,
            error=str(exc), **trace_context,
        )
        target.exception(
            "LLM call failed call_id=%s component=%s purpose=%s",
            call_id, component, purpose,
        )
        raise

    elapsed_ms = round((perf_counter() - started) * 1000, 2)
    details = _response_details(response)
    log_event(
        target, "llm.response", call_id=call_id, component=component,
        purpose=purpose, elapsed_ms=elapsed_ms, **details, **trace_context,
    )
    usage = safe_for_log(details.get("usage"))
    target.info(
        "LLM completed call_id=%s component=%s purpose=%s model=%s "
        "elapsed_ms=%.2f usage=%s",
        call_id, component, purpose, details.get("model") or model,
        elapsed_ms, json.dumps(usage, ensure_ascii=False, separators=(",", ":")),
    )
    return response
