def palindrome_checker(text: str) -> bool:
    normalized = ''.join(char.lower() for char in text if char.isalnum())
    return normalized == normalized[::-1]
