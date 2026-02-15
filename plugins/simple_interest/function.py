def simple_interest(principal: float, rate_percent: float, time_years: float) -> float:
    if principal < 0 or rate_percent < 0 or time_years < 0:
        raise ValueError("principal, rate_percent, and time_years must be non-negative")
    interest = principal * (rate_percent / 100) * time_years
    return round(interest, 2)
