RATES_TO_USD = {
    'usd': 1.0,
    'eur': 1.08,
    'gbp': 1.25,
}


def currency_converter(amount: float, from_currency: str, to_currency: str) -> float:
    from_currency = from_currency.lower()
    to_currency = to_currency.lower()
    if from_currency not in RATES_TO_USD or to_currency not in RATES_TO_USD:
        raise ValueError('Unsupported currency code')
    usd_amount = amount / RATES_TO_USD[from_currency]
    target_amount = usd_amount * RATES_TO_USD[to_currency]
    return round(target_amount, 2)
