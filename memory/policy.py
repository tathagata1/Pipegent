from __future__ import annotations

import re
from dataclasses import replace

from memory.domain import (
    MemoryDecision, MemoryPolicyInput, MemoryPolicyResult, MemorySource, MemoryType,
)


class MemoryPolicyEngine:
    SECRET_PATTERNS = (
        re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{16,}\b"),
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        re.compile(r"\b(?:password|passwd|api[_ -]?key|access[_ -]?token|session cookie)\s*[:=]",
                   re.IGNORECASE),
        re.compile(r"\b(?:cvv|cvc)\s*[:=]?\s*\d{3,4}\b", re.IGNORECASE),
    )
    SENSITIVE = {
        "health", "financial", "authentication", "identity", "precise_location",
        "third_party_personal", "politics", "ethnicity", "sexuality", "beliefs",
    }

    def __init__(
        self, auto_confidence: float = 0.90, auto_importance: float = 0.70,
        max_content_characters: int = 12000,
    ) -> None:
        self.auto_confidence = auto_confidence
        self.auto_importance = auto_importance
        self.max_content_characters = max_content_characters

    def evaluate(self, value: MemoryPolicyInput) -> MemoryPolicyResult:
        candidate = value.candidate
        content = " ".join(candidate.content.strip().split())
        if not content:
            return MemoryPolicyResult(MemoryDecision.REJECT, ["Memory content is empty."])
        if len(content) > self.max_content_characters:
            return MemoryPolicyResult(MemoryDecision.REJECT, ["Memory exceeds size limit."])
        if any(pattern.search(content) for pattern in self.SECRET_PATTERNS):
            return MemoryPolicyResult(MemoryDecision.REJECT, ["Secret-like content is prohibited."])
        normalised = replace(
            candidate, content=content,
            confidence=min(1.0, max(0.0, candidate.confidence)),
            importance=min(1.0, max(0.0, candidate.importance)),
        )
        if candidate.source == MemorySource.AGENT_INFERRED:
            normalised = replace(
                normalised,
                proposed_type=(
                    MemoryType.OBSERVATION
                    if candidate.proposed_type in {MemoryType.USER_FACT, MemoryType.USER_PREFERENCE}
                    else candidate.proposed_type
                ),
            )
        if candidate.sensitivity.casefold() in self.SENSITIVE:
            return MemoryPolicyResult(
                MemoryDecision.REQUEST_CONFIRMATION,
                ["Sensitive information requires explicit confirmation."], normalised,
            )
        if candidate.requires_confirmation or (
            candidate.source == MemorySource.AGENT_INFERRED
            and value.user_consent_required
        ):
            return MemoryPolicyResult(
                MemoryDecision.REQUEST_CONFIRMATION,
                ["Inferred or uncertain memory requires confirmation."], normalised,
            )
        if not value.explicit_user_request:
            if not value.automatic_memory_enabled:
                return MemoryPolicyResult(
                    MemoryDecision.IGNORE, ["Automatic memory is disabled."], normalised
                )
            if normalised.confidence < self.auto_confidence:
                return MemoryPolicyResult(
                    MemoryDecision.IGNORE, ["Confidence is below automatic threshold."],
                    normalised,
                )
            if normalised.importance < self.auto_importance:
                return MemoryPolicyResult(
                    MemoryDecision.IGNORE, ["Importance is below automatic threshold."],
                    normalised,
                )
            if candidate.source not in {
                MemorySource.USER_IMPLICIT, MemorySource.EXECUTION_RESULT,
                MemorySource.USER_EXPLICIT,
            }:
                return MemoryPolicyResult(
                    MemoryDecision.IGNORE, ["Source is not reliable enough for automatic storage."],
                    normalised,
                )
        return MemoryPolicyResult(MemoryDecision.STORE, ["Candidate is eligible."], normalised)
