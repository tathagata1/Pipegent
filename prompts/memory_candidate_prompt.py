MEMORY_CANDIDATE_PROMPT = """Analyse the latest user interaction and verified task results.
Identify only standalone information likely to remain useful in future conversations or tasks.
Do not extract filler, temporary emotions, unsupported assumptions, hidden reasoning, secrets,
credentials, duplicates, or information useful only for the current answer.
Return structured JSON: {"candidates": [{"content": string, "proposed_type": string,
"proposed_scope": string, "source": string, "reason": string, "confidence": number,
"importance": number, "estimated_lifetime": string, "sensitivity": string,
"requires_confirmation": boolean, "source_message_ids": [string]}]}.
Return an empty candidate list when nothing should be remembered."""
