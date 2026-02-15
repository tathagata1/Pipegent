def percentage_of_total(value: float, total: float) -> float:
    if total == 0:
        raise ValueError("total cannot be zero")
    return round((value / total) * 100, 4)
