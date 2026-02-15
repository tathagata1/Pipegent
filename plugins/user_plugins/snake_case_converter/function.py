import re


def snake_case_converter(text: str) -> str:
    text = re.sub(r'[^0-9a-zA-Z]+', ' ', text)
    parts = text.strip().split()
    return '_'.join(part.lower() for part in parts)
