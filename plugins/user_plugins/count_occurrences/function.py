def count_occurrences(text: str, substring: str) -> int:
    if not substring:
        raise ValueError('substring cannot be empty')
    return text.count(substring)
