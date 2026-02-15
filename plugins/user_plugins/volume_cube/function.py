def volume_cube(side: float) -> float:
    if side < 0:
        raise ValueError("side must be non-negative")
    return round(side ** 3, 4)
