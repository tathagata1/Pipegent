from typing import Any, List


def unique_values(items: List[Any]) -> List[Any]:
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
