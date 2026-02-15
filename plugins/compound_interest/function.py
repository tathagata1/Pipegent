def compound_interest(principal: float, rate_percent: float, times_per_year: int, years: float) -> float:
    if principal < 0 or rate_percent < 0 or times_per_year <= 0 or years < 0:
        raise ValueError("Invalid inputs for compound interest calculation")
    rate = rate_percent / 100
    amount = principal * (1 + rate / times_per_year) ** (times_per_year * years)
    return round(amount, 2)
