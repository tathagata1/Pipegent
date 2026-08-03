"""Formatting helpers for the minimal interactive terminal UI."""

from __future__ import annotations

import json
from typing import Any


def display_message(reply: Any) -> str:
    """Return a structured reply's user-facing message, or its original text."""
    text = str(reply).strip()
    candidate = text
    if candidate.startswith("```"):
        first_newline = candidate.find("\n")
        if first_newline != -1:
            candidate = candidate[first_newline + 1:]
            if candidate.rstrip().endswith("```"):
                candidate = candidate.rstrip()[:-3].rstrip()
    try:
        payload = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        return text
    if isinstance(payload, dict):
        for key in ("message", "final_answer", "final_message"):
            message = payload.get(key)
            if isinstance(message, str) and message.strip():
                return message.strip()
    return text
