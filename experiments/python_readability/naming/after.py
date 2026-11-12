def remaining(capacity, reserved):
    available = capacity - reserved
    if available < 0:
        return 0
    return available
