"""Legacy mode gate. M1a intentionally does not connect the EDL to rendering."""
VALID_MODES = {"off", "shadow", "on"}

def edl_mode(params):
    if not isinstance(params, dict): return "off"
    value = params.get("edl_mode", "off")
    return value if isinstance(value, str) and value in VALID_MODES else "off"

def should_render_edl(params):
    """Only an explicit on value opts in; this module does not render anything."""
    return edl_mode(params) == "on"
