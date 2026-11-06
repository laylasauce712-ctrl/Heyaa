"""Pure frame/time math using rational frame rates."""
from fractions import Fraction
import math
from .schema import EDLValidationError, require_int

def _fps(num, den):
    require_int(num, "fps_num", 1); require_int(den, "fps_den", 1)
    return Fraction(num, den)

def frames_to_seconds(frames, fps_num, fps_den=1):
    require_int(frames, "frames")
    return float(Fraction(frames, 1) / _fps(fps_num, fps_den))

def seconds_to_frames(seconds, fps_num, fps_den=1):
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
        raise EDLValidationError("seconds must be a finite number >= 0")
    value = Fraction(str(seconds)) * _fps(fps_num, fps_den)
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)

def timeline_end_frame(items):
    end = 0
    for i, item in enumerate(items):
        if not isinstance(item, dict): raise EDLValidationError(f"items[{i}] must be an object")
        start = require_int(item.get("start_f"), f"items[{i}].start_f")
        duration = require_int(item.get("dur_f"), f"items[{i}].dur_f", 1)
        end = max(end, start + duration)
    return end
