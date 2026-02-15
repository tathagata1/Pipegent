def tip_calculator(amount: float, tip_percent: float, split_between: int = 1) -> dict:
    if amount < 0:
        raise ValueError("amount must be non-negative")
    if tip_percent < 0:
        raise ValueError("tip_percent must be non-negative")
    if split_between <= 0:
        raise ValueError("split_between must be at least 1")

    tip = amount * (tip_percent / 100)
    total = amount + tip
    per_person = total / split_between
    return {
        "tip": round(tip, 2),
        "total": round(total, 2),
        "per_person": round(per_person, 2)
    }
