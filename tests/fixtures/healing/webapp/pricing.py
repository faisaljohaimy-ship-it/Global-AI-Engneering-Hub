"""Order quotes in integer cents. Orders of ten or more units get 15% off."""


def quote(unit_price_cents, quantity):
    if unit_price_cents < 0 or quantity < 1:
        raise ValueError("unit price must be >= 0 and quantity >= 1")
    total = unit_price_cents * quantity
    if quantity > 10:
        total = total * 85 // 100
    return total
