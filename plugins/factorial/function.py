import math


def factorial(n: int) -> int:
    if n < 0 or n > 1000:
        raise ValueError('n must be between 0 and 1000')
    return math.factorial(n)
