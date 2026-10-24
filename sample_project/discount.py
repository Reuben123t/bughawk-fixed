def discounted_price(price: float, discount_percent: float) -> float:
    return price - (price * discount_percent / 100)
