import tempfile
import unittest
from pathlib import Path

from scripts.watch_agents import (
    format_agent_report,
    format_progress_event,
    latest_run_dir,
)


class WatchAgentsTests(unittest.TestCase):
    def test_latest_run_directory_uses_timestamp_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "runs" / "20261027-100000-000001").mkdir(parents=True)
            newest = root / "runs" / "20261029-140000-000001"
            newest.mkdir(parents=True)
            self.assertEqual(latest_run_dir(root), newest)

    def test_agent_event_shows_findings_recommendations_and_evidence(self):
        event = {
            "timestamp": "2026-10-29T14:00:00Z",
            "stage": "agent:beat_sync_agent",
            "status": "insufficient_evidence",
            "summary": "No reliable beat candidates.",
            "details": {
                "agent_event": {
                    "agent": "beat_sync_agent",
                    "data": {
                        "findings": ["Zero beat candidates measured."],
                        "recommendations": ["Keep fallback timing and flag the missing evidence."],
                        "evidence": {"candidate_count": 0, "method": "low-frequency onset envelope"},
                        "score": None,
                        "confidence": 0.0,
                    },
                }
            },
        }
        output = "\n".join(format_progress_event(event))
        self.assertIn("beat_sync_agent", output)
        self.assertIn("Zero beat candidates measured.", output)
        self.assertIn("Keep fallback timing", output)
        self.assertIn('"candidate_count": 0', output)
        self.assertIn("confidence=0.0", output)

    def test_pre_render_review_event_identifies_speaker_and_target(self):
        event = {
            "timestamp": "2026-10-29T14:00:00Z",
            "stage": "pre_render_agent_review",
            "status": "completed",
            "summary": "No usable reference profile.",
            "details": {
                "speaker": "Reference Analyst",
                "to": "Planner",
                "evidence": {"median_cut_interval_seconds": None},
            },
        }
        output = "\n".join(format_progress_event(event))
        self.assertIn("Reference Analyst -> Planner", output)
        self.assertIn("median_cut_interval_seconds", output)

    def test_final_report_shows_director_decision_and_missing_evidence(self):
        report = {
            "status": "ready_for_human_review",
            "summary": "Technical gates passed.",
            "human_review_required": True,
            "results": {
                "niche_analyst": {
                    "status": "insufficient_evidence",
                    "score": None,
                    "confidence": 0.0,
                    "findings": ["Still missing: beat_alignment, drop_impact."],
                    "recommendations": ["Measure missing signals before ranking."],
                    "evidence": {"missing_metrics": ["beat_alignment", "drop_impact"]},
                }
            },
            "agent_dialogue": [{
                "speaker": "Niche Analyst", "to": "Director",
                "message": "Do not invent a craft score.",
                "evidence": {"missing_metrics": ["beat_alignment", "drop_impact"]},
            }],
        }
        output = "\n".join(format_agent_report(report))
        self.assertIn("ready_for_human_review", output)
        self.assertIn("Still missing: beat_alignment, drop_impact.", output)
        self.assertIn("Niche Analyst -> Director", output)
        self.assertIn("not private LLM chain-of-thought", output)


if __name__ == "__main__":
    unittest.main()
