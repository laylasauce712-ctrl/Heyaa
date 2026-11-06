"""Lightweight, dependency-free Phonk drop-transition scoring.

This detects a sustained low-frequency energy rise around an onset. It is an
evidence-based drop candidate, not semantic understanding of music.
"""
from __future__ import annotations

import math
import statistics
from typing import Iterable


def choose_drop_candidate(
    energies: Iterable[float],
    onset_candidates: Iterable[tuple[float, float]],
    *,
    hop_seconds: float = 0.02,
    pre_seconds: float = 0.75,
    post_seconds: float = 0.70,
    minimum_rise_ratio: float = 1.35,
    minimum_sustain_ratio: float = 0.65,
    minimum_score: float = 0.62,
) -> dict | None:
    """Return the strongest sustained low-band energy transition, or None."""
    values = []
    for value in energies:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        number = float(value)
        if math.isfinite(number) and number >= 0:
            values.append(number)
    if (
        isinstance(hop_seconds, bool)
        or not isinstance(hop_seconds, (int, float))
        or not math.isfinite(float(hop_seconds))
        or hop_seconds <= 0
        or len(values) < 40
    ):
        return None
    hop = float(hop_seconds)
    pre_count = max(5, int(round(pre_seconds / hop)))
    post_count = max(5, int(round(post_seconds / hop)))
    if len(values) < pre_count + post_count + 1:
        return None

    candidates = []
    for item in onset_candidates:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            continue
        strength, timestamp = item
        if (
            isinstance(strength, bool) or isinstance(timestamp, bool)
            or not isinstance(strength, (int, float))
            or not isinstance(timestamp, (int, float))
            or not math.isfinite(float(strength))
            or not math.isfinite(float(timestamp))
            or float(timestamp) < 0
        ):
            continue
        index = int(round(float(timestamp) / hop))
        if index < pre_count or index + post_count > len(values):
            continue
        candidates.append((float(strength), float(timestamp), index))
    if not candidates:
        return None

    typical_energy = statistics.median(values)
    positive_strengths = [max(0.0, item[0]) for item in candidates]
    typical_strength = statistics.median(positive_strengths) if positive_strengths else 0.0
    strongest_strength = max(positive_strengths, default=0.0)
    strength_spread = max(1e-12, strongest_strength - typical_strength)

    scored = []
    for strength, timestamp, index in candidates:
        before = values[index - pre_count:index]
        after = values[index:index + post_count]
        split = max(1, len(after) // 2)
        first_half = after[:split]
        second_half = after[split:]
        pre_mean = sum(before) / len(before)
        post_mean = sum(after) / len(after)
        first_mean = sum(first_half) / len(first_half)
        second_mean = sum(second_half) / len(second_half)
        if pre_mean <= 1e-9 or post_mean <= 1e-9:
            continue
        rise_ratio = post_mean / pre_mean
        sustain_ratio = min(first_mean, second_mean) / post_mean
        onset_score = max(0.0, min(1.0, (max(0.0, strength) - typical_strength) / strength_spread))
        rise_score = max(0.0, min(1.0, (rise_ratio - 1.15) / (2.20 - 1.15)))
        sustain_score = max(0.0, min(1.0, (sustain_ratio - 0.45) / 0.55))
        global_support = max(0.0, min(1.0, post_mean / max(1e-9, typical_energy * 1.25)))
        score = 0.55 * rise_score + 0.20 * sustain_score + 0.15 * onset_score + 0.10 * global_support
        scored.append({
            "timestamp_seconds": round(timestamp, 4),
            "confidence": round(score, 4),
            "pre_low_band_rms": round(pre_mean, 6),
            "post_low_band_rms": round(post_mean, 6),
            "rise_ratio": round(rise_ratio, 4),
            "sustain_ratio": round(sustain_ratio, 4),
            "onset_strength": round(strength, 6),
            "method": "low_band_sustained_energy_transition",
            "semantic_drop_understanding": False,
        })
    if not scored:
        return None
    best = max(scored, key=lambda result: result["confidence"])
    if (
        best["rise_ratio"] < minimum_rise_ratio
        or best["sustain_ratio"] < minimum_sustain_ratio
        or best["confidence"] < minimum_score
    ):
        return None
    return best
