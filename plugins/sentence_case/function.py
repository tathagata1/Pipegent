def sentence_case(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return text
    return stripped[0].upper() + stripped[1:].lower()
