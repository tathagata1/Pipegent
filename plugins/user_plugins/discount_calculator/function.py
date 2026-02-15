def discount_calculator(price: float, discount_percent: float) -> dict:
    if price < 0 or discount_percent < 0:
        raise ValueError("price and discount_percent must be non-negative")
    discount = price * (discount_percent / 100)
    final_price = price - discount
    return {"discount_amount": round(discount, 2), "final_price": round(final_price, 2)}
