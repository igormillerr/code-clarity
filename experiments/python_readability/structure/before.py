def shipping_fee(order):
    fee = None
    if order["paid"]:
        if order["items"] > 0:
            if order["destination"] == "local":
                if order["priority"]:
                    fee = 900
                else:
                    fee = 500
            else:
                fee = 1500
    return fee
