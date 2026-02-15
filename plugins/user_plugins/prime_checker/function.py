def prime_checker(value: int) -> bool:
    if value < 2:
        return False
    if value in (2, 3):
        return True
    if value % 2 == 0 or value % 3 == 0:
        return False
    i = 5
    while i * i <= value:
        if value % i == 0 or value % (i + 2) == 0:
            return False
        i += 6
    return True
