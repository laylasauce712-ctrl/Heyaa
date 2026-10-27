import unittest
import tempfile
from pathlib import Path

from src.heyaa.agents import (
    beat_sync_agent, director_agent, export_storage_agent, framing_agent, hook_analyst,
    inspector, media_analyst, niche_analyst, planner, reference_analyst,
    run_agent_team, settings_agent,
)


def config():
    return {
        "style": "phonk_montagem",
        "video_settings": {"resolution": "1080x1920", "fps": 24, "codec": "libx264", "crf": 26, "preset": "ultrafast"},
        "edit_settings": {"duration_seconds": 8, "speed": 1.1, "freeze_duration": 0.35, "edl_mode": "on",
                          "min_clips": 6, "max_clips": 6, "reference_pacing": False,
                          "mirror_enabled": False, "smart_crop": True},
        "audio_settings": {"beat_sync": False, "beat_flash": False, "bass_boost": False, "music_loop": True},
    }


def sample_edl():
    clips = []
    cursor = 0
    durations = [26, 25, 25, 26, 25, 25]
    for i, duration in enumerate(durations):
        source_duration = round(duration * 1.1)
        clips.append({
            "type": "clip", "source": "input/test_video.mp4",
            "source_start_f": i * 30, "source_dur_f": source_duration,
            "start_f": cursor, "dur_f": duration, "speed": 1.1,
            "crop": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
        })
        cursor += duration
    clips.append({"type": "freeze", "source": "timeline:last_frame", "source_frame_f": cursor - 1,
                  "start_f": cursor, "dur_f": 192 - cursor, "effect": "phonk-freeze"})
    return {
        "version": 1, "fps_num": 24, "fps_den": 1, "width": 1080, "height": 1920, "total_frames": 192,
        "video": clips,
        "audio": [{"source": "input/phonk.mp3", "source_start_f": 0, "start_f": 0, "dur_f": 192,
                   "gain_db": 0.0, "fade_out_f": 19}],
    }

def render_report():
    return {"width": 1080, "height": 1920, "duration_seconds": 8.0, "expected_duration_seconds": 8.0,
            "fps": 24.0, "expected_fps": 24, "video_codec": "h264", "expected_video_codec": "h264",
            "frame_count": 192, "expected_frame_count": 192, "has_audio": True, "decode_ok": True, "file_exists": True, "audio_codec": "aac"}


class AgentTests(unittest.TestCase):
    def test_settings_agent_checks_config_not_hard_coded_speed_or_crop(self):
        cfg = config()
        cfg["edit_settings"]["speed"] = 1.2
        cfg["edit_settings"]["smart_crop"] = False
        self.assertEqual(settings_agent(cfg).status, "ok")

    def test_settings_agent_rejects_boolean_numeric_settings(self):
        cfg = config()
        cfg["edit_settings"]["speed"] = True
        result = settings_agent(cfg)
        self.assertEqual(result.status, "blocked")
        self.assertTrue(any("speed" in finding for finding in result.findings))
        cfg = config()
        cfg["edit_settings"]["duration_seconds"] = True
        self.assertEqual(settings_agent(cfg).status, "blocked")

    def test_settings_agent_blocks_unsupported_settings(self):
        cfg = config()
        cfg["video_settings"]["fps"] = 120
        result = settings_agent(cfg)
        self.assertEqual(result.status, "blocked")
        self.assertTrue(any("fps" in finding for finding in result.findings))

    def test_niche_agent_refuses_missing_evidence(self):
        result = niche_analyst({"beat_alignment": 0.8}, ["phonk", "montagem"])
        self.assertEqual(result.status, "insufficient_evidence")
        self.assertIsNone(result.score)
        self.assertIn("visual_clarity", result.evidence["missing_metrics"])
        self.assertEqual(result.evidence["viral_prediction"], "not_available")

    def test_niche_score_is_heuristic_not_viral_promise(self):
        metrics = {key: 0.9 for key in ("beat_alignment", "visual_clarity", "hook_strength", "drop_impact", "motion_energy")}
        result = niche_analyst(metrics, ["phonk", "montagem", "beat_sync"])
        self.assertEqual(result.status, "ok")
        self.assertGreaterEqual(result.score, 80)
        self.assertEqual(result.evidence["viral_prediction"], "not_guaranteed")

    def test_inspector_rejects_wrong_frames_decode_or_missing_audio(self):
        report = render_report()
        report.update({"height": 1080, "frame_count": 191, "decode_ok": False, "has_audio": False})
        result = inspector(report)
        self.assertEqual(result.status, "reject")
        self.assertTrue(any("1080x1920" in item for item in result.findings))
        self.assertTrue(any("frame" in item.lower() for item in result.findings))
        self.assertTrue(any("decode" in item.lower() for item in result.findings))
        self.assertTrue(any("Audio" in item for item in result.findings))

    def test_planner_checks_edl_against_params(self):
        ctx = {"settings": config(), "edl": sample_edl()}
        result = planner(ctx)
        self.assertEqual(result.status, "ok", result.findings)


    def test_planner_rejects_unimplemented_crop_and_wrong_clip_count(self):
        edl = sample_edl()
        edl["video"][0]["crop"] = {"x": 0.1, "y": 0.0, "w": 0.9, "h": 1.0}
        result = planner({"settings": config(), "edl": edl})
        self.assertEqual(result.status, "needs_fix")
        self.assertIn("unsupported_crop_indices", result.evidence["mismatches"])
        cfg = config()
        cfg["edit_settings"]["min_clips"] = 7
        cfg["edit_settings"]["max_clips"] = 7
        result = planner({"settings": cfg, "edl": sample_edl()})
        self.assertEqual(result.status, "needs_fix")
        self.assertIn("clip_count", result.evidence["mismatches"])

    def test_media_and_beat_agents_report_evidence(self):
        media = media_analyst({"source_duration_seconds": 10.0, "source_width": 640, "source_height": 360,
                               "scene_cut_count": 5, "music_duration_seconds": 20.0})
        self.assertEqual(media.status, "ok")
        beat = beat_sync_agent({"enabled": True, "candidate_count": 0, "fallback": "even_pacing"})
        self.assertEqual(beat.status, "insufficient_evidence")


    def test_reference_agent_reports_fallback_not_fake_reference_results(self):
        result = reference_analyst({"enabled": True, "available": False, "source": None,
                                    "median_cut_interval_seconds": None})
        self.assertEqual(result.status, "insufficient_evidence")
        self.assertFalse(result.evidence["used_for_planning"])

    def test_framing_agent_rejects_ignored_edl_crop(self):
        edl = sample_edl()
        edl["video"][0]["crop"] = {"x": 0.2, "y": 0.0, "w": 0.8, "h": 1.0}
        result = framing_agent(config(), edl)
        self.assertEqual(result.status, "needs_fix")

    def test_hook_agent_never_claims_semantic_hook_score_from_scene_changes(self):
        result = hook_analyst({"window_seconds": 2.0, "opening_scene_change_count": 3})
        self.assertEqual(result.status, "insufficient_evidence")
        self.assertIsNone(result.score)
        self.assertFalse(result.evidence["semantic_hook_assessed"])


    def test_agents_fail_closed_on_malformed_context(self):
        self.assertEqual(settings_agent(None).status, "blocked")
        self.assertEqual(media_analyst(None).status, "insufficient_evidence")
        self.assertEqual(hook_analyst(None).status, "insufficient_evidence")
        self.assertEqual(inspector(None).status, "reject")

    def test_director_makes_explicit_export_decision(self):
        result = run_agent_team({
            "settings": config(), "edl": sample_edl(),
            "media_analysis": {"source_duration_seconds": 10.0, "source_width": 640, "source_height": 360,
                               "scene_cut_count": 5, "music_duration_seconds": 9.0},
            "beat_analysis": {"enabled": False, "candidate_count": 0},
            "render_report": render_report(),
        })
        director = result["results"]["director"]
        self.assertEqual(director["status"], "ready_for_human_review")
        self.assertEqual(director["evidence"]["decision"], "allow_technical_export")
        self.assertTrue(result["human_review_required"])
        blocked = director_agent({"settings_agent": settings_agent(None)})
        self.assertEqual(blocked.status, "blocked")
        self.assertEqual(blocked.evidence["decision"], "block_export")

    def test_export_storage_preserves_previous_final_when_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            final = Path(folder) / "final.mp4"
            temp = Path(folder) / "temporary.mp4"
            final.write_bytes(b"known-good")
            temp.write_bytes(b"new-render")
            blocked = export_storage_agent(str(temp), str(final), False)
            self.assertEqual(blocked.status, "blocked")
            self.assertEqual(final.read_bytes(), b"known-good")
            self.assertTrue(temp.exists())
            allowed = export_storage_agent(str(temp), str(final), True)
            self.assertEqual(allowed.status, "ok")
            self.assertEqual(final.read_bytes(), b"new-render")
            self.assertFalse(temp.exists())

    def test_team_emits_all_actual_structured_stages_and_blocks_missing_qa(self):
        emitted = []
        result = run_agent_team({
            "settings": config(), "edl": sample_edl(),
            "media_analysis": {"source_duration_seconds": 10.0, "source_width": 640, "source_height": 360,
                               "scene_cut_count": 5, "music_duration_seconds": 9.0},
            "beat_analysis": {"enabled": False, "candidate_count": 0},
            "niche_metrics": {}, "niche_tags": ["phonk", "montagem"],
            "render_report": render_report(),
        }, emit=emitted.append)
        self.assertEqual(result["status"], "ready_for_human_review")
        self.assertEqual(len(emitted), 10)
        self.assertEqual(emitted, result["events"])
        self.assertFalse(result["viral_guarantee"])
        self.assertEqual(result["results"]["niche_analyst"]["status"], "insufficient_evidence")
        self.assertIn("planner", result["results"])
        self.assertIn("director", result["results"])
        self.assertEqual(result["results"]["hook_analyst"]["status"], "insufficient_evidence")
        self.assertEqual(result["results"]["reference_analyst"]["status"], "skipped")
        self.assertEqual(result["results"]["framing_agent"]["status"], "ok")
        broken = run_agent_team({"settings": config(), "edl": sample_edl(), "render_report": {}})
        self.assertEqual(broken["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
