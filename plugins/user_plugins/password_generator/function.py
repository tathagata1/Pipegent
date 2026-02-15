import random
import string

DEFAULT_SYMBOLS = "!@#$%^&*()-_=+[]{};:,.?/"

def password_generator(length: int = 12, include_digits: bool = True, include_symbols: bool = True) -> str:
    if length < 4:
        raise ValueError("length must be at least 4 characters")

    charset = list(string.ascii_letters)
    if include_digits:
        charset.extend(string.digits)
    if include_symbols:
        charset.extend(DEFAULT_SYMBOLS)

    if not charset:
        raise ValueError("Character set is empty")

    return "".join(random.choice(charset) for _ in range(length))
