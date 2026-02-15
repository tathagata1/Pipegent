def percentage_change(old_value: float, new_value: float) -> float:
    if old_value == 0:
        raise ValueError("old_value cannot be zero")
    change = ((new_value - old_value) / abs(old_value)) * 100
    return round(change, 4)
