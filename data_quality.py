import math
from typing import Optional, Sequence, Tuple

MAX_ABS_VELOCITY_PX_PER_MIN = 200.0
CORE_RATIO_MIN = 0.0
CORE_RATIO_MAX = 1.0
ECCENTRICITY_MIN = 0.0
ECCENTRICITY_MAX = 1.0
CAPE_MIN_JKG = 0.0
CAPE_MAX_JKG = 5000.0
CLOUD_TOP_MIN_MSL = -1.0
CLOUD_TOP_MAX_MSL = 20000.0
MAX_TARGET_JUMP_PX = 600.0


def _is_finite_number(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _iter_values(value):
    """Liefert nur numerische Blatt-Werte (int/float). Strings, None,
    bool und andere nicht-numerische Typen werden übersprungen."""
    if isinstance(value, dict):
        for item in value.values():
            yield from _iter_values(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_values(item)
    elif hasattr(value, "shape") and hasattr(value, "ravel"):
        for item in value.ravel().tolist():
            if isinstance(item, (int, float)):
                yield item
    elif isinstance(value, (int, float)):
        yield value
    # Strings, None, bool → werden nicht geliefert


def validate_sample(seq, target) -> Tuple[bool, Optional[str]]:
    if not all(_is_finite_number(v) for v in _iter_values(seq)) or not all(
        _is_finite_number(v) for v in _iter_values(target)
    ):
        return False, "non-finite values"

    if not seq:
        return False, "empty sequence"

    for frame in seq:
        if not isinstance(frame, dict):
            continue

        vx = float(frame.get("vx", 0.0))
        vy = float(frame.get("vy", 0.0))
        if abs(vx) > MAX_ABS_VELOCITY_PX_PER_MIN or abs(vy) > MAX_ABS_VELOCITY_PX_PER_MIN:
            return False, "velocity out of range"

        core_ratio = float(frame.get("core_ratio", 0.0))
        if not (CORE_RATIO_MIN <= core_ratio <= CORE_RATIO_MAX):
            return False, "core_ratio out of range"

        eccentricity = float(frame.get("eccentricity", frame.get("cell_eccentricity", 0.0)))
        if not (ECCENTRICITY_MIN <= eccentricity <= ECCENTRICITY_MAX):
            return False, "eccentricity out of range"

        cape = float(frame.get("cape", frame.get("cell_cape_jkg", 0.0)))
        if not (CAPE_MIN_JKG <= cape <= CAPE_MAX_JKG):
            return False, "cape out of range"

        cloud_top = float(frame.get("cloud_top_height_msl", frame.get("cell_cloud_top_height_msl", -1.0)))
        if not (CLOUD_TOP_MIN_MSL <= cloud_top <= CLOUD_TOP_MAX_MSL):
            return False, "cloud_top_height_msl out of range"

    current_obj = seq[-1] if isinstance(seq[-1], dict) else {}
    current_x = float(current_obj.get("x", 0.0))
    current_y = float(current_obj.get("y", 0.0))

    target_x_30 = float(target[4]) if len(target) >= 6 else float(target[0])
    target_y_30 = float(target[5]) if len(target) >= 6 else float(target[1])
    jump = math.hypot(target_x_30 - current_x, target_y_30 - current_y)
    if jump > MAX_TARGET_JUMP_PX:
        return False, "target jump too large"

    return True, None
