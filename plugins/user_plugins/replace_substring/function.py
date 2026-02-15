def replace_substring(text: str, old: str, new: str) -> str:
    if not old:
        raise ValueError('old value cannot be empty')
    return text.replace(old, new)
