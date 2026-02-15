def number_rounder(value: float, decimals: int = 0) -> float:
    if decimals < 0 or decimals > 10:
        raise ValueError('decimals must be between 0 and 10')
    return round(value, decimals)
