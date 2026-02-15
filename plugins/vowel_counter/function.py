VOWELS = set('aeiou')


def vowel_counter(text: str) -> int:
    return sum(1 for char in text.lower() if char in VOWELS)
