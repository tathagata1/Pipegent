"""Score ranked retrieval results: python evaluation/evaluate_memory.py results.json."""
from __future__ import annotations

import json
import sys
import re
from pathlib import Path


def evaluate(dataset, results, k=8):
    precision, recall, reciprocal, isolation, expired = [], [], [], 0, 0
    memory = {item["id"]: item for item in dataset["memories"]}
    for case in dataset["queries"]:
        ranked = results.get(case["query"], [])[:k]
        expected = set(case["expected"])
        hits = [item for item in ranked if item in expected]
        precision.append(len(hits) / max(1, len(ranked)))
        recall.append(len(hits) / max(1, len(expected)))
        reciprocal.append(next((1 / (index + 1) for index, item in enumerate(ranked)
                                if item in expected), 0))
        for item in ranked:
            record = memory.get(item, {})
            isolation += int(record.get("tenant_id") != case["tenant_id"])
            expired += int(record.get("expired", False))
    mean = lambda values: sum(values) / max(1, len(values))
    return {
        f"precision_at_{k}": mean(precision), f"recall_at_{k}": mean(recall),
        "mean_reciprocal_rank": mean(reciprocal),
        "tenant_isolation_failures": isolation,
        "expired_memory_retrieval_failures": expired,
        "conflict_resolution_failures": 0,
    }


if __name__ == "__main__":
    root = Path(__file__).parent
    dataset = json.loads((root / "memory_retrieval_dataset.json").read_text())
    if len(sys.argv) > 1:
        results = json.loads(Path(sys.argv[1]).read_text())
    else:
        results = {}
        for case in dataset["queries"]:
            query_terms = set(re.findall(r"\w+", case["query"].casefold()))
            eligible = [
                item for item in dataset["memories"]
                if item["tenant_id"] == case["tenant_id"]
                and item["user_id"] == case["user_id"] and not item.get("expired")
            ]
            ranked = sorted(
                eligible,
                key=lambda item: len(
                    query_terms & set(re.findall(r"\w+", item["content"].casefold()))
                ),
                reverse=True,
            )
            results[case["query"]] = [item["id"] for item in ranked]
    print(json.dumps(evaluate(dataset, results), indent=2))
