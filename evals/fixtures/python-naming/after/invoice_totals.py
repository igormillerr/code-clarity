def subtotal(a):
    b = [(x["quantity"], x["unit_price"]) for x in a]
    return sum(x * y for x, y in b)
