import unittest
from src.heyaa.agents import inspector, niche_analyst, run_agent_team


class AgentTests(unittest.TestCase):
    def test_niche_agent_refuses_missing_evidence(self):
        result = niche_analyst({}, ["phonk", "montagem"])
        self.assertEqual(result.status, "insufficient_evidence")
        self.assertIsNone(result.score)
        self.assertEqual(result.evidence["viral_prediction"], "not_available")

    def test_niche_score_is_heuristic_not_viral_promise(self):
        metrics = {key: 0.9 for key in (
            "beat_alignment", "visual_clarity", "hook_strength", "drop_impact", "motion_energy")}
        result = niche_analyst(metrics, ["phonk", "montagem", "beat_sync"])
        self.assertEqual(result.status, "ok")
        self.assertGreaterEqual(result.score, 80)
        self.assertEqual(result.evidence["viral_prediction"], "not_guaranteed")

    def test_inspector_rejects_square_or_missing_audio(self):
        result = inspector({"width": 1080, "height": 1080, "duration_seconds": 20, "has_audio": False})
        self.assertEqual(result.status, "reject")
        self.assertTrue(any("1080x1920" in item for item in result.findings))
        self.assertTrue(any("Audio" in item for item in result.findings))

    def test_team_emits_real_structured_events_and_blocks(self):
        emitted = []
        result = run_agent_team({
            "settings": {"resolution": "1080x1920", "speed": 1.1, "smart_crop": True},
            "niche_metrics": {},
            "render_report": {"width": 1080, "height": 1920, "duration_seconds": 20, "has_audio": True},
        }, emit=emitted.append)
        self.assertEqual(result["status"], "ready_for_human_review")
        self.assertEqual(len(emitted), 3)
        self.assertEqual(emitted, result["events"])
        self.assertFalse(result["viral_guarantee"])
        self.assertEqual(result["results"]["niche_analyst"]["status"], "insufficient_evidence")


if __name__ == "__main__":
    unittest.main()
