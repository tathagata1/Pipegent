import re

WORD_RE = re.compile(r"\b\w+\b", re.UNICODE)

def word_counter(text: str) -> dict:
    words = WORD_RE.findall(text)
    return {
        "words": len(words),
        "characters": len(text),
        "unique_words": len(set(word.lower() for word in words))
    }
