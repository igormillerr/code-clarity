def shipping_fee(order):
    if not order["paid"]:
        return None
    if order["items"] <= 0:
        return None
    if order["destination"] != "local":
        return 1500
    if order["priority"]:
        return 900
    return 500
