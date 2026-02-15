from typing import List


def substring_finder(text: str, substring: str) -> List[int]:
    if not substring:
        raise ValueError('substring cannot be empty')
    indexes = []
    start = 0
    while True:
        idx = text.find(substring, start)
        if idx == -1:
            break
        indexes.append(idx)
        start = idx + 1
    return indexes
