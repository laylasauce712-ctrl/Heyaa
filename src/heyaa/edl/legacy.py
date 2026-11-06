"""Compatibility helper for old callers with top-level `edl_mode`.

The active renderer uses `edit_settings.edl_mode` in params.json and consumes
EDL directly. This helper is retained only for callers/tests of the old shape.
"""
VALID_MODES = {"off", "shadow", "on"}

def edl_mode(params):
    if not isinstance(params, dict): return "off"
    value = params.get("edl_mode", "off")
    return value if isinstance(value, str) and value in VALID_MODES else "off"

def should_render_edl(params):
    """Legacy predicate only; this helper does not perform rendering."""
    return edl_mode(params) == "on"
