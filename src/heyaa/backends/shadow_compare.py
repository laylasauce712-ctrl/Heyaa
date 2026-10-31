"""Pure helpers for comparing scene-cut candidates without selecting a winner."""
from __future__ import annotations

import math
from typing import Iterable


def compare_cut_timestamps(
    primary: Iterable[float],
    shadow: Iterable[float],
    *,
    tolerance_seconds: float = 0.15,
) -> dict:
    """Measure timestamp agreement between two sorted-or-unsorted cut lists.

    Neither source is treated as ground truth. The result deliberately avoids
    precision/recall terminology and reports only one-to-one temporal agreement.
    """
    if (
        isinstance(tolerance_seconds, bool)
        or not isinstance(tolerance_seconds, (int, float))
        or not math.isfinite(float(tolerance_seconds))
        or tolerance_seconds < 0
    ):
        raise ValueError("tolerance_seconds must be a finite number >= 0")

    def normalize(values: Iterable[float], name: str) -> list[float]:
        result = []
        for value in values:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or value < 0
            ):
                raise ValueError(f"{name} timestamps must be finite numbers >= 0")
            result.append(float(value))
        return sorted(result)

    left = normalize(primary, "primary")
    right = normalize(shadow, "shadow")
    i = j = 0
    matches: list[dict[str, float]] = []
    tolerance = float(tolerance_seconds)

    while i < len(left) and j < len(right):
        delta = right[j] - left[i]
        if abs(delta) <= tolerance:
            matches.append({
                "primary_seconds": left[i],
                "shadow_seconds": right[j],
                "absolute_delta_seconds": round(abs(delta), 6),
            })
            i += 1
            j += 1
        elif delta > tolerance:
            i += 1
        else:
            j += 1

    shared = len(matches)
    return {
        "tolerance_seconds": tolerance,
        "primary_cut_count": len(left),
        "shadow_cut_count": len(right),
        "shared_cut_count": shared,
        "primary_only_count": len(left) - shared,
        "shadow_only_count": len(right) - shared,
        "mean_shared_delta_seconds": (
            round(sum(item["absolute_delta_seconds"] for item in matches) / shared, 6)
            if shared else None
        ),
        "matches": matches,
        "interpretation": "agreement only; neither detector is ground truth",
    }
