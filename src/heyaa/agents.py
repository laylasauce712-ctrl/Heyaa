"""Structured, evidence-first agent orchestration for Heyaa.

These are deterministic agents, not independent LLMs. They inspect actual
settings, media-analysis outputs, EDL and render-QA data. Missing evidence is
reported as missing; it is never invented to create a score.
"""
from dataclasses import asdict, dataclass
import math
from typing import Any, Callable

try:
    from src.heyaa.edl.validate import validate_edl
except ModuleNotFoundError:
    from heyaa.edl.validate import validate_edl


@dataclass(frozen=True)
class AgentEvent:
    agent: str
    stage: str
    status: str
    summary: str
    data: dict[str, Any]


@dataclass(frozen=True)
class AgentResult:
    agent: str
    status: str
    score: float | None
    confidence: float
    findings: tuple[str, ...]
    recommendations: tuple[str, ...]
    evidence: dict[str, Any]


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def settings_agent(config: dict[str, Any]) -> AgentResult:
    """Validate actual params.json values, not a hard-coded preferred profile."""
    findings: list[str] = []
    if not isinstance(config, dict):
        return AgentResult("settings_agent", "blocked", None, 0.0,
                           ("Settings payload must be an object.",), ("Repair params.json before rendering.",), {})
    video = config.get("video_settings", {})
    edit = config.get("edit_settings", {})
    audio = config.get("audio_settings", {})
    if not all(isinstance(x, dict) for x in (video, edit, audio)):
        return AgentResult("settings_agent", "blocked", None, 0.0,
                           ("video_settings, edit_settings and audio_settings must be objects.",),
                           ("Repair params.json before rendering.",), {})
    if config.get("style") != "phonk_montagem":
        findings.append("Only style='phonk_montagem' is implemented.")
    if str(video.get("resolution", "")).lower() != "1080x1920":
        findings.append("This renderer's required output is 1080x1920 (9:16).")
    fps = video.get("fps")
    if not isinstance(fps, int) or isinstance(fps, bool) or not 24 <= fps <= 60:
        findings.append("video_settings.fps must be an integer from 24 to 60.")
    duration = edit.get("duration_seconds")
    if not _finite_number(duration) or not 8 <= float(duration) <= 60:
        findings.append("edit_settings.duration_seconds must be between 8 and 60.")
    speed = edit.get("speed")
    if not _finite_number(speed) or not 1.0 <= float(speed) <= 1.35:
        findings.append("edit_settings.speed must be between 1.0x and 1.35x.")
    freeze = edit.get("freeze_duration")
    if (not _finite_number(freeze) or not _finite_number(duration) or
            not 0.35 <= float(freeze) <= 1.2 or float(freeze) >= float(duration)):
        findings.append("freeze_duration must be 0.35–1.2 seconds and shorter than the edit.")
    for key in ("mirror_enabled", "smart_crop", "reference_pacing"):
        if not isinstance(edit.get(key), bool):
            findings.append(f"edit_settings.{key} must be an explicit boolean.")
    for key in ("beat_sync", "beat_flash", "bass_boost", "music_loop"):
        if not isinstance(audio.get(key), bool):
            findings.append(f"audio_settings.{key} must be an explicit boolean.")
    if edit.get("edl_mode") != "on":
        findings.append("edit_settings.edl_mode must be 'on'.")
    minimum, maximum = edit.get("min_clips"), edit.get("max_clips")
    if (not isinstance(minimum, int) or isinstance(minimum, bool) or
            not isinstance(maximum, int) or isinstance(maximum, bool) or
            not 6 <= minimum <= 12 or not minimum <= maximum <= 18):
        findings.append("Clip bounds must satisfy 6 <= min_clips <= 12 and min_clips <= max_clips <= 18.")
    crf = video.get("crf")
    if not isinstance(crf, int) or isinstance(crf, bool) or not 16 <= crf <= 26:
        findings.append("video_settings.crf must be an integer from 16 to 26.")
    preset = video.get("preset")
    if preset not in {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"}:
        findings.append("video_settings.preset is not an implemented x264 preset.")
    if video.get("codec") != "libx264":
        findings.append("Only video_settings.codec='libx264' is currently implemented.")
    if findings:
        return AgentResult("settings_agent", "blocked", None, 1.0,
                           tuple(findings), ("Correct params.json; unsupported settings must fail fast, not silently change.",),
                           {"resolution": video.get("resolution"), "fps": fps, "duration_seconds": duration,
                            "speed": speed, "freeze_duration": freeze})
    return AgentResult("settings_agent", "ok", None, 1.0,
                       ("All required settings are present and within renderer-supported bounds.",), (),
                       {"resolution": video["resolution"], "fps": fps, "duration_seconds": duration,
                        "speed": speed, "freeze_duration": freeze,
                        "mirror_enabled": edit["mirror_enabled"], "smart_crop": edit["smart_crop"],
                        "music_loop": audio["music_loop"], "edl_mode": edit["edl_mode"]})


def media_analyst(media: dict[str, Any]) -> AgentResult:
    """Report measured source metadata; do not interpret scene cuts as semantics."""
    if not isinstance(media, dict):
        media = {}
    required = ("source_duration_seconds", "source_width", "source_height", "scene_cut_count",
                "music_duration_seconds")
    missing = [key for key in required if key not in media or media[key] is None]
    invalid = [key for key in required if key in media and media[key] is not None and
               (not _finite_number(media[key]) or float(media[key]) < 0)]
    for key in ("source_width", "source_height", "source_duration_seconds", "music_duration_seconds"):
        if key in media and _finite_number(media[key]) and float(media[key]) <= 0 and key not in invalid:
            invalid.append(key)
    if missing or invalid:
        return AgentResult("media_analyst", "insufficient_evidence", None, 0.0,
                           ("Source metadata is incomplete or invalid.",),
                           ("Probe the source video and soundtrack before planning.",),
                           {"missing_fields": missing, "invalid_fields": invalid})
    return AgentResult("media_analyst", "ok", None, 0.9,
                       ("Source duration, dimensions, detected scene-cut count and music duration were measured.",
                        "Scene-cut detection is a visual-change heuristic; it does not identify semantic scenes."),
                       (), {key: media[key] for key in required})


def beat_sync_agent(analysis: dict[str, Any]) -> AgentResult:
    if not isinstance(analysis, dict):
        analysis = {}
    enabled = analysis.get("enabled") is True
    count = analysis.get("candidate_count", 0)
    fallback = analysis.get("fallback")
    if not enabled:
        return AgentResult("beat_sync_agent", "skipped", None, 0.0,
                           ("Beat sync is disabled in params.json.",), (),
                           {"enabled": False, "candidate_count": 0})
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        return AgentResult("beat_sync_agent", "blocked", None, 0.0,
                           ("Beat candidate count is invalid.",), (), {"candidate_count": count})
    if count < 3 or fallback == "even_pacing":
        return AgentResult("beat_sync_agent", "insufficient_evidence", None, 0.0,
                           ("No stable beat sequence was available; even pacing fallback was used.",),
                           ("Keep fallback timing and expose low beat confidence; do not claim beat-accurate cuts.",),
                           {"enabled": True, "candidate_count": count, "fallback": "even_pacing",
                            "method": analysis.get("method", "unknown")})
    return AgentResult("beat_sync_agent", "ok", None, 0.45,
                       ("Bass-onset candidates were detected by a lightweight heuristic.",),
                       ("Review beat alignment visually; candidates are not guaranteed downbeats.",),
                       {"enabled": True, "candidate_count": count, "fallback": None,
                        "method": analysis.get("method", "unknown"),
                        "tempo_bpm": analysis.get("tempo_bpm")})


def planner(context: dict[str, Any]) -> AgentResult:
    """Check the actual EDL against the requested config and integer-frame target."""
    if not isinstance(context, dict):
        context = {}
    config = context.get("settings", {})
    video = config.get("video_settings", {}) if isinstance(config, dict) else {}
    edit = config.get("edit_settings", {}) if isinstance(config, dict) else {}
    edl = context.get("edl")
    if not isinstance(edl, dict):
        return AgentResult("planner", "blocked", None, 0.0,
                           ("The renderer did not provide an EDL.",),
                           ("Build and validate the EDL before rendering.",), {"edl_present": False})
    try:
        validate_edl(edl)
    except (TypeError, ValueError, KeyError) as exc:
        return AgentResult("planner", "blocked", None, 1.0,
                           (f"EDL validation failed: {exc}",), ("Repair the EDL before export.",),
                           {"edl_present": True, "validation_error": str(exc)})
    mismatches: dict[str, Any] = {}
    resolution = str(video.get("resolution", "")).lower().split("x")
    try:
        if len(resolution) != 2:
            raise ValueError("expected WIDTHxHEIGHT")
        expected_size = (int(resolution[0]), int(resolution[1]))
    except (TypeError, ValueError):
        mismatches["resolution"] = {"actual": video.get("resolution")}
    else:
        if (edl.get("width"), edl.get("height")) != expected_size:
            mismatches["dimensions"] = {"expected": expected_size, "actual": (edl.get("width"), edl.get("height"))}
    fps = video.get("fps")
    if isinstance(fps, int) and not isinstance(fps, bool):
        if edl.get("fps_num") != fps:
            mismatches["fps_num"] = {"expected": fps, "actual": edl.get("fps_num")}
        if edl.get("fps_den") != 1:
            mismatches["fps_den"] = {"expected": 1, "actual": edl.get("fps_den")}
    duration = edit.get("duration_seconds")
    if _finite_number(duration) and isinstance(fps, int) and not isinstance(fps, bool):
        expected_frames = round(float(duration) * fps)
        if edl.get("total_frames") != expected_frames:
            mismatches["total_frames"] = {"expected": expected_frames, "actual": edl.get("total_frames")}
    target_speed = edit.get("speed")
    if not _finite_number(target_speed):
        mismatches["settings_speed"] = {"actual": target_speed}
    else:
        bad_speed = [i for i, item in enumerate(edl.get("video", []))
                     if item.get("type") == "clip" and
                     abs(float(item.get("speed")) - float(target_speed)) > 1e-6]
        if bad_speed:
            mismatches["clip_speed_indices"] = bad_speed
    if mismatches:
        return AgentResult("planner", "needs_fix", None, 1.0,
                           ("The validated EDL does not match params.json.",),
                           ("Regenerate the EDL from the normalized settings; do not patch settings silently.",),
                           {"mismatches": mismatches, "total_frames": edl.get("total_frames"),
                            "video_items": len(edl.get("video", []))})
    return AgentResult("planner", "ok", None, 1.0,
                       ("EDL schema, frame continuity, speed, dimensions and target frame count match params.json.",), (),
                       {"edl_present": True, "edl_version": edl["version"], "fps_num": edl["fps_num"],
                        "fps_den": edl["fps_den"], "total_frames": edl["total_frames"],
                        "video_items": len(edl["video"]), "audio_items": len(edl.get("audio", [])),
                        "frame_contiguous": True})


def reference_analyst(data: dict[str, Any]) -> AgentResult:
    """Report measured reference pacing only when a reference was actually analyzed."""
    if not isinstance(data, dict):
        data = {}
    if data.get("enabled") is not True:
        return AgentResult("reference_analyst", "skipped", None, 0.0,
                           ("Reference pacing is disabled in params.json.",), (),
                           {"enabled": False, "used_for_planning": False})
    interval = data.get("median_cut_interval_seconds")
    if data.get("available") is not True or not _finite_number(interval) or float(interval) <= 0:
        return AgentResult("reference_analyst", "insufficient_evidence", None, 0.0,
                           ("No usable reference pacing profile was measured; the renderer uses its default rhythm.",),
                           ("Provide a valid reference.mp4 or disable reference pacing.",),
                           {"enabled": True, "available": data.get("available") is True,
                            "used_for_planning": False, "source": data.get("source")})
    return AgentResult("reference_analyst", "ok", None, 0.8,
                       ("Median reference cut interval was measured and used only as a rough pacing guide.",),
                       ("Review the resulting rhythm against the actual soundtrack.",),
                       {"enabled": True, "available": True, "used_for_planning": True,
                        "source": data.get("source"),
                        "median_cut_interval_seconds": round(float(interval), 4),
                        "does_not_copy_reference_frames": True})


def framing_agent(config: dict[str, Any], edl: dict[str, Any]) -> AgentResult:
    """Check that the EDL framing can be represented by the current renderer."""
    edit = config.get("edit_settings", {}) if isinstance(config, dict) else {}
    if not isinstance(edl, dict) or not isinstance(edl.get("video"), list):
        return AgentResult("framing_agent", "blocked", None, 0.0,
                           ("EDL video list is missing or invalid.",), ("Build a valid EDL before framing review.",), {})
    clips = [item for item in edl["video"] if isinstance(item, dict) and item.get("type") == "clip"]
    if not clips:
        return AgentResult("framing_agent", "blocked", None, 0.0,
                           ("No video clips were available to inspect for framing.",),
                           ("Build a valid EDL before framing review.",), {"clip_count": 0})
    unsupported = []
    for index, item in enumerate(clips):
        crop = item.get("crop", {})
        if not isinstance(crop, dict):
            unsupported.append(index)
            continue
        expected = (("x", 0.0), ("y", 0.0), ("w", 1.0), ("h", 1.0))
        malformed = any(not _finite_number(crop.get(key)) for key, _ in expected)
        if malformed or any(abs(float(crop[key]) - value) > 1e-6 for key, value in expected):
            unsupported.append(index)
    if unsupported:
        return AgentResult("framing_agent", "needs_fix", None, 1.0,
                           ("EDL contains per-shot crop rectangles the current FFmpeg renderer does not implement.",),
                           ("Use the supported full-source crop or implement and test arbitrary EDL crop rectangles before rendering.",),
                           {"unsupported_crop_indices": unsupported, "clip_count": len(clips)})
    smart_crop = edit.get("smart_crop")
    mirror = edit.get("mirror_enabled")
    mode = "center_crop_9_16" if smart_crop is True else "blurred_background_legacy"
    recs = []
    findings = ["Every EDL clip uses the framing mode currently implemented by FFmpeg."]
    if mirror is True:
        recs.append("Mirroring is active; inspect any visible text because horizontal flipping reverses writing.")
    findings.append("Framing mode is centered aspect crop, not face/subject tracking." if smart_crop is True
                    else "Legacy blurred-background framing is explicitly selected.")
    return AgentResult("framing_agent", "ok", None, 1.0, tuple(findings), tuple(recs),
                       {"mode": mode, "mirror_enabled": mirror, "clip_count": len(clips),
                        "subject_tracking": False, "arbitrary_crop_rectangles_supported": False})


def hook_analyst(data: dict[str, Any]) -> AgentResult:
    """Measure an opening-pacing proxy without pretending it understands semantic hooks."""
    if not isinstance(data, dict):
        data = {}
    count = data.get("opening_scene_change_count")
    window = data.get("window_seconds")
    if (not isinstance(count, int) or isinstance(count, bool) or count < 0 or
            not _finite_number(window) or float(window) <= 0):
        return AgentResult("hook_analyst", "insufficient_evidence", None, 0.0,
                           ("No valid opening-window analysis was supplied.",),
                           ("Run the opening-window scene-change probe before review.",),
                           {"semantic_hook_assessed": False})
    return AgentResult("hook_analyst", "insufficient_evidence", None, 0.0,
                       ("Opening scene changes were measured, but semantic hook strength was not assessed.",),
                       ("Human-review the first seconds for a clear subject, readable action and immediate reason to keep watching.",
                        "Do not use scene-change count alone as a hook score."),
                       {"measurement": data.get("measurement", "ffmpeg_scene_change"),
                        "window_seconds": float(window), "opening_scene_change_count": count,
                        "semantic_hook_assessed": False, "hook_strength_score": None})


def niche_analyst(metrics: dict[str, Any], tags: list[str] | None = None) -> AgentResult:
    """Score craft only when measured signals are supplied; never predict virality."""
    if not isinstance(metrics, dict):
        metrics = {}
    tags = tags if isinstance(tags, list) else []
    required = ("beat_alignment", "visual_clarity", "hook_strength", "drop_impact", "motion_energy")
    parsed = {}
    invalid = []
    for key in required:
        value = metrics.get(key)
        if value is None:
            continue
        if not _finite_number(value) or not 0.0 <= float(value) <= 1.0:
            invalid.append(key)
        else:
            parsed[key] = float(value)
    supported = {"phonk", "montagem", "beat_sync", "freeze", "impact_cut", "vertical"}
    matching = sorted({str(tag).strip().lower() for tag in tags} & supported)
    missing = [key for key in required if key not in parsed]
    if invalid:
        return AgentResult("niche_analyst", "blocked", None, 0.0,
                           ("Some craft metrics are invalid.",), ("Provide measured normalized values in [0, 1].",),
                           {"invalid_metrics": invalid, "missing_metrics": missing})
    if missing:
        findings = ["Insufficient evidence to score all required craft signals.",
                    "A craft score is not a prediction of reach, views or virality."]
        recommendations = ["Measure the missing signals before ranking the edit."]
        if not matching:
            recommendations.append("Confirm the intended niche tags.")
        return AgentResult("niche_analyst", "insufficient_evidence", None, 0.0,
                           tuple(findings), tuple(recommendations),
                           {"measured_metrics": parsed, "missing_metrics": missing,
                            "matched_tags": matching, "viral_prediction": "not_available"})
    weights = {"beat_alignment": 0.28, "visual_clarity": 0.22, "hook_strength": 0.20,
               "drop_impact": 0.18, "motion_energy": 0.12}
    score = round(sum(parsed[key] * weights[key] for key in required) * 100, 1)
    recs = []
    if parsed["beat_alignment"] < 0.7:
        recs.append("Re-time the strongest cuts to measured beat candidates, then verify by eye.")
    if parsed["visual_clarity"] < 0.7:
        recs.append("Fix crop and subject visibility before adding effects.")
    if parsed["hook_strength"] < 0.7:
        recs.append("Improve the opening visual hook.")
    if parsed["drop_impact"] < 0.7:
        recs.append("Improve contrast into the drop/freeze without stacking effects blindly.")
    if parsed["motion_energy"] < 0.7:
        recs.append("Review clip pacing and motion changes.")
    return AgentResult("niche_analyst", "ok", score, 0.6,
                       ("This weighted craft score is heuristic and is not a virality prediction.",),
                       tuple(recs), {"metrics": parsed, "weights": weights, "matched_tags": matching,
                                     "viral_prediction": "not_guaranteed"})


def inspector(report: dict[str, Any]) -> AgentResult:
    """Require actual render evidence; missing QA data is a failure, not a pass."""
    if not isinstance(report, dict):
        report = {}
    required = ("width", "height", "duration_seconds", "expected_duration_seconds", "fps", "expected_fps",
                "frame_count", "expected_frame_count", "has_audio", "decode_ok", "file_exists",
                "video_codec", "expected_video_codec")
    missing = [key for key in required if key not in report]
    failures: list[str] = []
    if missing:
        failures.append("Missing render QA fields: " + ", ".join(missing))
    if report.get("width") != 1080 or report.get("height") != 1920:
        failures.append("Output must be 1080x1920 (9:16).")
    fps = report.get("fps")
    expected_fps = report.get("expected_fps")
    if not _finite_number(fps) or float(fps) <= 0:
        failures.append("Output FPS is missing or invalid.")
    elif not _finite_number(expected_fps) or abs(float(fps) - float(expected_fps)) > 0.01:
        failures.append(f"Output FPS {fps} does not match configured FPS {expected_fps}.")
    if report.get("video_codec") != report.get("expected_video_codec"):
        failures.append(f"Output video codec {report.get('video_codec')} does not match configured codec {report.get('expected_video_codec')}.")
    duration, expected = report.get("duration_seconds"), report.get("expected_duration_seconds")
    if not _finite_number(duration) or not _finite_number(expected) or float(expected) <= 0:
        failures.append("Output/target duration is missing or invalid.")
    elif abs(float(duration) - float(expected)) > (1.0 / float(fps) + 0.005 if _finite_number(fps) and fps > 0 else 0):
        failures.append("Output duration differs from target by more than one frame.")
    frame_count, expected_count = report.get("frame_count"), report.get("expected_frame_count")
    if not isinstance(frame_count, int) or isinstance(frame_count, bool) or frame_count <= 0:
        failures.append("Decoded video frame count is missing or invalid.")
    elif frame_count != expected_count:
        failures.append(f"Output has {frame_count} frames; expected exactly {expected_count}.")
    if report.get("has_audio") is not True:
        failures.append("Audio stream is missing.")
    if report.get("decode_ok") is not True:
        failures.append("Full-file decode check did not pass.")
    if report.get("file_exists") is not True:
        failures.append("Rendered output file is missing.")
    status = "reject" if failures else "ok"
    return AgentResult("inspector", status, None, 1.0 if not failures else 0.99,
                       tuple(failures or ["Frame count, dimensions, duration, FPS, audio and full decode checks passed."]),
                       ("Do not promote this render; fix failures and rerun QA.",) if failures else (),
                       {"checked_fields": list(required), "failures": failures,
                        "fps": fps, "frame_count": frame_count, "expected_frame_count": expected_count})


def run_agent_team(context: dict[str, Any],
                   emit: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Run each deterministic agent against the same real render context."""
    if not isinstance(context, dict):
        context = {}
    events: list[AgentEvent] = []

    def record(result: AgentResult, stage: str) -> None:
        event = AgentEvent(result.agent, stage, result.status,
                           result.findings[0] if result.findings else "Completed.",
                           {"score": result.score, "confidence": result.confidence,
                            "findings": list(result.findings),
                            "recommendations": list(result.recommendations),
                            "evidence": result.evidence})
        events.append(event)
        if emit:
            emit(asdict(event))

    settings = context.get("settings", {})
    setting_result = settings_agent(settings)
    record(setting_result, "settings_validation")
    media = media_analyst(context.get("media_analysis", {}))
    record(media, "media_analysis")
    beat = beat_sync_agent(context.get("beat_analysis", {}))
    record(beat, "beat_analysis")
    reference = reference_analyst(context.get("reference_analysis", {}))
    record(reference, "reference_analysis")
    framing = framing_agent(settings, context.get("edl", {}))
    record(framing, "framing_review")
    hook = hook_analyst(context.get("hook_analysis", {}))
    record(hook, "opening_hook_review")
    plan = planner(context)
    record(plan, "edl_planning")
    niche = niche_analyst(context.get("niche_metrics", {}), context.get("niche_tags", []))
    record(niche, "craft_review")
    qa = inspector(context.get("render_report", {}))
    record(qa, "render_qa")
    blocked = (setting_result.status != "ok" or plan.status != "ok" or
               framing.status in ("blocked", "needs_fix") or qa.status != "ok")
    status = "blocked" if blocked else "ready_for_human_review"
    return {
        "status": status,
        "viral_guarantee": False,
        "human_review_required": True,
        "summary": ("Technical QA blocked export; inspect failures." if blocked else
                    "Technical render QA passed; visual/human review is still required."),
        "results": {"settings_agent": asdict(setting_result), "media_analyst": asdict(media),
                    "beat_sync_agent": asdict(beat), "reference_analyst": asdict(reference),
                    "framing_agent": asdict(framing), "hook_analyst": asdict(hook),
                    "planner": asdict(plan), "niche_analyst": asdict(niche), "inspector": asdict(qa)},
        "render_report": dict(context.get("render_report", {})),
        "media_analysis": dict(context.get("media_analysis", {})),
        "beat_analysis": dict(context.get("beat_analysis", {})),
        "reference_analysis": dict(context.get("reference_analysis", {})),
        "hook_analysis": dict(context.get("hook_analysis", {})),
        "events": [asdict(event) for event in events],
    }
