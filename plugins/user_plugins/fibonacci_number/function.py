def fibonacci_number(n: int) -> int:
    if n < 0 or n > 92:
        raise ValueError('n must be between 0 and 92')
    if n in (0, 1):
        return n
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b
