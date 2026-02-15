import string

CONSONANTS = set(ch for ch in string.ascii_lowercase if ch not in 'aeiou')


def consonant_counter(text: str) -> int:
    return sum(1 for char in text.lower() if char in CONSONANTS)
