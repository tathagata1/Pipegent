import re


def camel_case_converter(text: str) -> str:
    text = re.sub(r'[^0-9a-zA-Z]+', ' ', text).strip()
    if not text:
        return ''
    parts = text.split()
    first = parts[0].lower()
    rest = [word.capitalize() for word in parts[1:]]
    return first + ''.join(rest)
