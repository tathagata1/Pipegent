MEMORY_RETRIEVAL_QUERY_PROMPT = """Given the current user message and active task, generate a
small set of long-term-memory search queries only when they could materially improve the answer.
Do not search for unrelated personal information. Return structured JSON:
{"primary_query": string, "alternate_queries": [string], "memory_types": [string],
"scopes": [string], "entities": [string], "time_constraints": {}}.
These fields are suggestions only; application code maps them through allowlisted filters."""
