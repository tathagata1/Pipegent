def savings_goal_calculator(target_amount: float, monthly_contribution: float, annual_rate_percent: float = 0.0) -> dict:
    if target_amount <= 0 or monthly_contribution <= 0:
        raise ValueError('target_amount and monthly_contribution must be positive')

    monthly_rate = annual_rate_percent / 100 / 12
    months = 0
    balance = 0.0
    while balance < target_amount and months <= 10000:
        balance = balance * (1 + monthly_rate) + monthly_contribution
        months += 1
    years = months / 12
    return {"months": months, "years": round(years, 2), "final_balance": round(balance, 2)}
