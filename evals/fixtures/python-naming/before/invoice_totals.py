def subtotal(line_items):
    return sum(item["quantity"] * item["unit_price"] for item in line_items)
