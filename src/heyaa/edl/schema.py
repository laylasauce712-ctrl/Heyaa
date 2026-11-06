"""Constants and validation primitives for EDL v1."""
EDL_VERSION = 1
MIN_SPEED = 0.25
MAX_SPEED = 4.0

class EDLValidationError(ValueError):
    """An edit decision list violates its declared contract."""

def require_int(value, field, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise EDLValidationError(f"{field} must be an integer >= {minimum}")
    return value
