def loan_payment(principal: float, annual_rate_percent: float, years: float) -> dict:
    if principal <= 0 or annual_rate_percent < 0 or years <= 0:
        raise ValueError("principal and years must be positive; rate cannot be negative")

    monthly_rate = annual_rate_percent / 100 / 12
    total_payments = int(years * 12)

    if monthly_rate == 0:
        payment = principal / total_payments
    else:
        payment = principal * (monthly_rate * (1 + monthly_rate) ** total_payments) / ((1 + monthly_rate) ** total_payments - 1)

    total_cost = payment * total_payments
    interest_paid = total_cost - principal
    return {
        "monthly_payment": round(payment, 2),
        "total_payment": round(total_cost, 2),
        "total_interest": round(interest_paid, 2)
    }
