"""CPU-friendly per-clip animation and look presets for distinct Heyaa edits."""
from __future__ import annotations

CREATIVE_PROFILE_ORDER = (
    "cinematic-impact",
    "aggressive-phonk",
    "smooth-motion",
    "hybrid-cinematic",
    "phonk-pulse",
)

CREATIVE_PROFILES = {
    "cinematic-impact": {
        "label": "Cinematic Impact",
        "description": "Measured push-ins, restrained camera drift, warm contrast and vignette.",
        "motion": "slow_push", "contrast": 1.22, "saturation": 1.16,
        "gamma": 1.01, "vignette": "PI/5",
    },
    "aggressive-phonk": {
        "label": "Aggressive Phonk",
        "description": "Short punch zooms, rhythmic micro-shake, punchier contrast and saturation.",
        "motion": "punch_shake", "contrast": 1.32, "saturation": 1.42,
        "gamma": 0.99, "vignette": None,
    },
    "smooth-motion": {
        "label": "Smooth Motion",
        "description": "Gentle continuous push and drift with a softer, cleaner grade.",
        "motion": "smooth_drift", "contrast": 1.10, "saturation": 1.12,
        "gamma": 1.04, "vignette": "PI/7",
    },
    "hybrid-cinematic": {
        "label": "Hybrid Cinematic",
        "description": "Alternates smooth push-ins and short impact pulses with a balanced grade.",
        "motion": "hybrid_alternating", "contrast": 1.18, "saturation": 1.25,
        "gamma": 1.02, "vignette": "PI/8",
    },
    "phonk-pulse": {
        "label": "Phonk Pulse",
        "description": "Sharper repeated punch zooms and strong saturated impact grading.",
        "motion": "pulse_zoom", "contrast": 1.28, "saturation": 1.48,
        "gamma": 0.99, "vignette": None,
    },
}


def get_creative_profile(profile_id: str) -> dict:
    """Return a defensive copy of a known profile, rejecting unknown names."""
    if profile_id not in CREATIVE_PROFILES:
        raise ValueError(
            f"Unknown creative profile {profile_id!r}; choose one of {', '.join(CREATIVE_PROFILE_ORDER)}."
        )
    return dict(CREATIVE_PROFILES[profile_id])


def profile_for_edit(edit_index: int) -> str:
    """Assign a stable, distinct visual treatment to each edit in a batch."""
    if isinstance(edit_index, bool) or not isinstance(edit_index, int) or edit_index < 1:
        raise ValueError("edit_index must be a positive integer.")
    if edit_index > len(CREATIVE_PROFILE_ORDER):
        raise ValueError(f"Only {len(CREATIVE_PROFILE_ORDER)} distinct creative profiles are defined.")
    return CREATIVE_PROFILE_ORDER[edit_index - 1]


def build_motion_filter(
    profile_id: str, clip_index: int, output_frames: int, fps: int, width: int, height: int,
) -> str:
    """Build a deterministic FFmpeg zoompan/look chain with fixed output dimensions."""
    profile = get_creative_profile(profile_id)
    for name, value in (("clip_index", clip_index), ("output_frames", output_frames),
                        ("fps", fps), ("width", width), ("height", height)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be an integer.")
    if clip_index < 0 or output_frames < 1 or fps < 1 or width < 2 or height < 2:
        raise ValueError("clip_index must be non-negative and frame/size values must be positive.")

    span = max(1, output_frames - 1)
    phase = (clip_index % 9) * 5
    motion = profile["motion"]
    if motion == "slow_push":
        zoom = f"1+0.065*on/{span}"
        pan_x = f"1.5*sin((on+{phase})*PI/54)"
        pan_y = f"1.5*cos((on+{phase})*PI/64)"
    elif motion == "punch_shake":
        zoom = f"1+0.055*abs(sin((on+{phase})*PI/10))"
        pan_x = f"5*sin((on+{phase})*PI/4)"
        pan_y = f"4*cos((on+{phase})*PI/5)"
    elif motion == "smooth_drift":
        zoom = f"1.02+0.03*on/{span}"
        pan_x = f"2*sin((on+{phase})*PI/90)"
        pan_y = f"1.5*cos((on+{phase})*PI/110)"
    elif motion == "pulse_zoom":
        zoom = f"1+0.065*abs(sin((on+{phase})*PI/8))"
        pan_x = f"4*sin((on+{phase})*PI/4)"
        pan_y = f"3*cos((on+{phase})*PI/5)"
    elif motion == "hybrid_alternating":
        if clip_index % 3 == 1:
            zoom = f"1+0.045*abs(sin((on+{phase})*PI/12))"
            pan_x = f"3.5*sin((on+{phase})*PI/5)"
            pan_y = f"2.5*cos((on+{phase})*PI/6)"
        else:
            zoom = f"1+0.052*on/{span}"
            pan_x = f"2*sin((on+{phase})*PI/60)"
            pan_y = f"2*cos((on+{phase})*PI/72)"
    else:
        raise ValueError(f"Unsupported motion mode {motion!r}.")

    chain = (
        f"zoompan=z='{zoom}':"
        f"x='iw/2-iw/zoom/2+{pan_x}':"
        f"y='ih/2-ih/zoom/2+{pan_y}':"
        f"d=1:s={width}x{height}:fps={fps},"
        f"eq=contrast={profile['contrast']:.3f}:"
        f"saturation={profile['saturation']:.3f}:gamma={profile['gamma']:.3f}"
    )
    if profile["vignette"]:
        chain += f",vignette={profile['vignette']}"
    return chain
