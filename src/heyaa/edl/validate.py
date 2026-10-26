"""Strict dependency-free validation for EDL version 1."""
import math
from .schema import EDL_VERSION, MIN_SPEED, MAX_SPEED, EDLValidationError, require_int
TOP = {"version","fps_num","fps_den","width","height","total_frames","video","audio"}
COMMON = {"type","start_f","dur_f"}
CLIP = COMMON | {"source","source_start_f","source_dur_f","speed","crop"}
FREEZE = COMMON | {"source","source_frame_f","effect"}
AUDIO = {"source","source_start_f","start_f","dur_f","gain_db","fade_in_f","fade_out_f"}

def _obj(v, name):
    if not isinstance(v, dict): raise EDLValidationError(f"{name} must be an object")
    return v

def _keys(v, allowed, name):
    extra = set(v) - allowed
    if extra: raise EDLValidationError(f"{name} has unknown field(s): {', '.join(sorted(extra))}")

def _num(v, name, lo=None, hi=None):
    if isinstance(v, bool) or not isinstance(v, (int,float)) or not math.isfinite(v): raise EDLValidationError(f"{name} must be a finite number")
    if lo is not None and v < lo: raise EDLValidationError(f"{name} must be >= {lo}")
    if hi is not None and v > hi: raise EDLValidationError(f"{name} must be <= {hi}")

def validate_edl(edl):
    """Validate and return an EDL; raise EDLValidationError on any contract violation."""
    edl = _obj(edl, "edl"); _keys(edl, TOP, "edl")
    version = require_int(edl.get("version"), "version", 1)
    if version != EDL_VERSION: raise EDLValidationError(f"unsupported EDL version: {version}")
    require_int(edl.get("fps_num"), "fps_num", 1); require_int(edl.get("fps_den",1), "fps_den", 1)
    require_int(edl.get("width"), "width", 1); require_int(edl.get("height"), "height", 1)
    total = require_int(edl.get("total_frames"), "total_frames", 1)
    video = edl.get("video")
    if not isinstance(video, list) or not video: raise EDLValidationError("video must be a non-empty list")
    cursor = 0
    for i, raw in enumerate(video):
        name = f"video[{i}]"; item = _obj(raw, name); kind = item.get("type")
        if kind == "clip": _keys(item, CLIP, name)
        elif kind == "freeze": _keys(item, FREEZE, name)
        else: raise EDLValidationError(f"{name}.type must be 'clip' or 'freeze'")
        start = require_int(item.get("start_f"), f"{name}.start_f")
        dur = require_int(item.get("dur_f"), f"{name}.dur_f", 1)
        if start != cursor: raise EDLValidationError(f"{name} must start at frame {cursor}; got {start}")
        cursor = start + dur
        if not isinstance(item.get("source"), str) or not item["source"].strip(): raise EDLValidationError(f"{name}.source must be a non-empty string")
        if kind == "clip":
            require_int(item.get("source_start_f"), f"{name}.source_start_f")
            source_dur = require_int(item.get("source_dur_f"), f"{name}.source_dur_f", 1)
            speed = item.get("speed", 1.0); _num(speed, f"{name}.speed", MIN_SPEED, MAX_SPEED)
            if abs(dur - source_dur / speed) > 1: raise EDLValidationError(f"{name}.dur_f inconsistent with source_dur_f / speed")
            crop = _obj(item.get("crop"), f"{name}.crop"); _keys(crop, {"x","y","w","h"}, f"{name}.crop")
            if set(crop) != {"x","y","w","h"}: raise EDLValidationError(f"{name}.crop must contain x, y, w, h")
            for key in ("x","y","w","h"): _num(crop[key], f"{name}.crop.{key}", 0, 1)
            if crop["w"] <= 0 or crop["h"] <= 0 or crop["x"] + crop["w"] > 1.000001 or crop["y"] + crop["h"] > 1.000001: raise EDLValidationError(f"{name}.crop must be a positive rectangle inside [0, 1]")
        else:
            require_int(item.get("source_frame_f"), f"{name}.source_frame_f")
            effect = item.get("effect", "freeze")
            if not isinstance(effect, str) or not effect.strip(): raise EDLValidationError(f"{name}.effect must be a non-empty string")
    if cursor != total: raise EDLValidationError(f"video timeline ends at frame {cursor}, total_frames is {total}")
    audio = edl.get("audio", [])
    if not isinstance(audio, list): raise EDLValidationError("audio must be a list")
    for i, raw in enumerate(audio):
        name=f"audio[{i}]"; item=_obj(raw,name); _keys(item,AUDIO,name)
        if not isinstance(item.get("source"),str) or not item["source"].strip(): raise EDLValidationError(f"{name}.source must be a non-empty string")
        for key in ("source_start_f","start_f","dur_f"): require_int(item.get(key),f"{name}.{key}",1 if key=="dur_f" else 0)
        if item["start_f"] + item["dur_f"] > total: raise EDLValidationError(f"{name} extends beyond total_frames")
        _num(item.get("gain_db",0.0),f"{name}.gain_db")
        for key in ("fade_in_f","fade_out_f"):
            if key in item and require_int(item[key],f"{name}.{key}") > item["dur_f"]: raise EDLValidationError(f"{name}.{key} cannot exceed dur_f")
    return edl
