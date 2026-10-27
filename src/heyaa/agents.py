"""Deterministic agent team contracts for Heyaa.

This is a rule-based orchestration baseline, not an LLM swarm and not a viral guarantee.
Agents return structured findings; every event is emitted from actual execution.
"""
from dataclasses import asdict, dataclass
from typing import Any, Callable


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


def _unit_interval(metrics: dict[str, Any], key: str) -> float | None:
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not 0.0 <= float(value) <= 1.0:
        return None
    return float(value)


def niche_analyst(metrics: dict[str, Any], tags: list[str] | None = None) -> AgentResult:
    """Score observable Phonk/Montagem craft signals, never claim guaranteed virality."""
    tags = tags or []
    required = ("beat_alignment", "visual_clarity", "hook_strength", "drop_impact", "motion_energy")
    parsed = {key: _unit_interval(metrics, key) for key in required}
    missing = [key for key, value in parsed.items() if value is None]
    niche_tags = {str(tag).strip().lower() for tag in tags}
    supported_tags = {"phonk", "montagem", "beat_sync", "freeze", "impact_cut", "vertical"}
    matching = sorted(niche_tags & supported_tags)
    findings = []
    recommendations = []
    if missing:
        findings.append("Insufficient evidence: required signals are missing or outside [0, 1].")
        recommendations.append("Measure the missing signals before ranking this edit.")
        return AgentResult("niche_analyst", "insufficient_evidence", None, 0.0,
                           tuple(findings), tuple(recommendations),
                           {"missing_metrics": missing, "supported_niche_tags": matching,
                            "viral_prediction": "not_available"})
    weights = {
        "beat_alignment": 0.28,
        "visual_clarity": 0.22,
        "hook_strength": 0.20,
        "drop_impact": 0.18,
        "motion_energy": 0.12,
    }
    score = round(sum(parsed[key] * weight for key, weight in weights.items()) * 100, 1)
    confidence = round(min(0.95, 0.45 + 0.08 * len(parsed) + (0.05 if matching else 0)), 2)
    if parsed["beat_alignment"] < 0.7:
        recommendations.append("Re-time the strongest cuts and freeze impact to verified beat transients.")
    if parsed["visual_clarity"] < 0.7:
        recommendations.append("Fix crop/framing and protect the main subject before adding more effects.")
    if parsed["hook_strength"] < 0.7:
        recommendations.append("Strengthen the opening moment; do not delay the first clear visual hook.")
    if parsed["drop_impact"] < 0.7:
        recommendations.append("Build a clearer contrast into the drop or freeze, without stacking effects blindly.")
    if not matching:
        recommendations.append("Confirm the edit's intended niche tags; niche fit is not yet evidenced.")
    findings.append("This is a craft-quality heuristic, not a prediction of views or virality.")
    if score >= 80:
        findings.append("Measured craft signals are strong; still require render QA and audience data.")
    elif score < 60:
        findings.append("Several craft signals need improvement before export.")
    return AgentResult("niche_analyst", "ok", score, confidence, tuple(findings),
                       tuple(recommendations),
                       {"metrics": parsed, "weights": weights, "matched_tags": matching,
                        "viral_prediction": "not_guaranteed"})


def planner(context: dict[str, Any]) -> AgentResult:
    settings = context.get("settings", {})
    required = {"resolution": "1080x1920", "speed": 1.1, "smart_crop": True}
    mismatches = {key: {"expected": expected, "actual": settings.get(key)}
                  for key, expected in required.items() if settings.get(key) != expected}
    recs = ("Synchronize settings across UI, Director and Renderer.",) if mismatches else ()
    return AgentResult("planner", "needs_fix" if mismatches else "ok", None,
                       1.0 if not mismatches else 0.95,
                       ("Validated baseline settings contract.",) if not mismatches else
                       ("Settings differ from the approved baseline.",),
                       recs, {"mismatches": mismatches})


def inspector(render_report: dict[str, Any]) -> AgentResult:
    required = ("width", "height", "duration_seconds", "has_audio")
    missing = [key for key in required if key not in render_report]
    failures = []
    if missing:
        failures.append("Missing render QA fields: " + ", ".join(missing))
    if render_report.get("width") != 1080 or render_report.get("height") != 1920:
        failures.append("Output must be 1080x1920 (9:16).")
    duration = render_report.get("duration_seconds")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or abs(duration - 20.0) > 0.3:
        failures.append("Output duration is outside the 20s target tolerance.")
    if render_report.get("has_audio") is not True:
        failures.append("Audio stream is missing.")
    return AgentResult("inspector", "reject" if failures else "ok", None,
                       1.0 if not failures else 0.99, tuple(failures or ["Basic render QA passed."]),
                       ("Re-render and re-run QA after fixing every failed check.",) if failures else (),
                       {"checked_fields": list(required), "failures": failures})


def run_agent_team(context: dict[str, Any],
                   emit: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Run deterministic stages and emit real events; no fabricated agent chat."""
    events: list[AgentEvent] = []

    def record(agent: str, stage: str, result: AgentResult) -> None:
        event = AgentEvent(agent, stage, result.status,
                           result.findings[0] if result.findings else "Completed.",
                           {"score": result.score, "confidence": result.confidence,
                            "recommendations": list(result.recommendations),
                            "evidence": result.evidence})
        events.append(event)
        if emit:
            emit(asdict(event))

    plan = planner(context)
    record("planner", "planning", plan)
    niche = niche_analyst(context.get("niche_metrics", {}), context.get("niche_tags", []))
    record("niche_analyst", "niche_review", niche)
    qa = inspector(context.get("render_report", {}))
    record("inspector", "render_qa", qa)
    blocked = plan.status != "ok" or qa.status != "ok" or niche.status != "ok"
    status = "blocked" if blocked else "ready_for_human_review"
    summary = {
        "status": status,
        "viral_guarantee": False,
        "human_review_required": True,
        "results": {"planner": asdict(plan), "niche_analyst": asdict(niche),
                    "inspector": asdict(qa)},
        "events": [asdict(event) for event in events],
    }
    return summary
