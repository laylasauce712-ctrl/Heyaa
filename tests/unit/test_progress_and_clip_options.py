import json
import tempfile
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch

from src import agent_director as renderer
from src.heyaa import agents as agent_modules
from src.heyaa.agents import AgentResult, run_agent_team
from src.heyaa.media_sources import parse_media_source_args


class ProgressTraceTests(unittest.TestCase):
    def test_progress_event_appends_machine_readable_jsonl(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(renderer, "OUTDIR", temporary), patch("builtins.print"):
                event = renderer.progress_event(
                    "render_clip", "completed", "Motion clip 1/8 rendered.",
                    {"clip_number": 1, "clip_total": 8},
                )
            path = Path(temporary) / "progress.jsonl"
            self.assertTrue(path.is_file())
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["stage"], "render_clip")
            self.assertEqual(rows[0]["status"], "completed")
            self.assertEqual(rows[0]["details"]["clip_number"], 1)
            self.assertEqual(event["summary"], "Motion clip 1/8 rendered.")
            self.assertTrue(rows[0]["timestamp"].endswith("Z"))

    def test_ai_upscaling_emits_extract_and_batch_progress(self):
        events = []
        with tempfile.TemporaryDirectory() as temporary:
            def fake_run(command, **kwargs):
                if command[0] == "ffmpeg":
                    pattern = Path(command[-1])
                    for frame in range(1, 3):
                        Path(str(pattern).replace("%08d", f"{frame:08d}")).write_bytes(b"fake-png")
                else:
                    output_dir = Path(command[command.index("-o") + 1])
                    for frame in range(1, 3):
                        (output_dir / f"frame_{frame:08d}.png").write_bytes(b"fake-upscaled-png")
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            def record(stage, status, summary, details=None, **kwargs):
                events.append((stage, status, summary, details or {}))

            with patch.object(renderer, "WORK", temporary), \
                 patch.object(renderer, "VIDEO", "input/test_video.mp4"), \
                 patch.object(renderer, "FPS", 24), \
                 patch.object(renderer, "AI_UPSCALE_ENABLED", True), \
                 patch.object(renderer, "AI_UPSCALER_EXECUTABLE", "fake-realesrgan"), \
                 patch.object(renderer, "AI_UPSCALER_MODEL_DIR", "fake-models"), \
                 patch.object(renderer, "AI_UPSCALE_MODEL", "realesrgan-x4plus"), \
                 patch.object(renderer, "AI_UPSCALE_SCALE", 2), \
                 patch.object(renderer, "progress_event", side_effect=record), \
                 patch("src.agent_director.subprocess.run", side_effect=fake_run):
                output_pattern, root = renderer.prepare_ai_upscaled_frames(0, 0.0, 1.0, 2)

            self.assertTrue((root / "upscaled" / "frame_00000001.png").is_file())
            self.assertEqual(output_pattern.parent, root / "upscaled")
            self.assertEqual([(stage, status) for stage, status, _, _ in events], [
                ("upscale_extract", "running"),
                ("upscale_extract", "completed"),
                ("upscale_batch", "running"),
                ("upscale_batch", "completed"),
            ])

    def test_exact_clip_count_override_respects_settings_bounds(self):
        with patch.object(renderer, "MIN_CLIPS", 8), patch.object(renderer, "MAX_CLIPS", 16):
            self.assertEqual(renderer.choose_clip_count(1.1, 12), 12)
            with self.assertRaisesRegex(ValueError, "outside params.json bounds"):
                renderer.choose_clip_count(1.1, 17)
            with self.assertRaisesRegex(ValueError, "must be an integer"):
                renderer.choose_clip_count(1.1, True)

    def test_clip_count_alternatives_parse_as_distinct_integer_options(self):
        args = parse_media_source_args([
            "--variants", "3", "--clip-count-options", "8,12,16",
        ])
        self.assertEqual(args.variants, 3)
        self.assertEqual(args.clip_count_options, (8, 12, 16))
        self.assertIsNone(args.clip_count)

    def test_exact_clip_count_cli_option_parses(self):
        args = parse_media_source_args(["--variants", "1", "--clip-count", "12"])
        self.assertEqual(args.clip_count, 12)
        self.assertIsNone(args.clip_count_options)

    def test_agent_lifecycle_emits_running_then_completed_events(self):
        progress_events = []
        completed_events = []

        def mocked_result(agent, evidence=None, status="ok"):
            return lambda *args, **kwargs: AgentResult(
                agent, status, None, 1.0, (f"{agent} fixture complete.",), (), evidence or {}
            )

        patches = [
            patch.object(agent_modules, "settings_agent", side_effect=mocked_result("settings_agent")),
            patch.object(agent_modules, "media_analyst", side_effect=mocked_result("media_analyst")),
            patch.object(agent_modules, "beat_sync_agent", side_effect=mocked_result(
                "beat_sync_agent", {"candidate_count": 3, "drop_beat_time_seconds": 1.0, "method": "test"}
            )),
            patch.object(agent_modules, "reference_analyst", side_effect=mocked_result(
                "reference_analyst", {"available": True, "median_cut_interval_seconds": 1.0, "shot_intervals_seconds": [1.0]}
            )),
            patch.object(agent_modules, "framing_agent", side_effect=mocked_result("framing_agent")),
            patch.object(agent_modules, "hook_analyst", side_effect=mocked_result(
                "hook_analyst", {"window_seconds": 2.0, "opening_scene_change_count": 1}
            )),
            patch.object(agent_modules, "planner", side_effect=mocked_result("planner")),
            patch.object(agent_modules, "niche_analyst", side_effect=mocked_result(
                "niche_analyst", {"missing_metrics": []}
            )),
            patch.object(agent_modules, "inspector", side_effect=mocked_result("inspector")),
            patch.object(agent_modules, "render_critic", side_effect=mocked_result("render_critic")),
            patch.object(agent_modules, "director_agent", side_effect=mocked_result(
                "director", {"decision": "allow_technical_export", "blockers": []}, "ready_for_human_review"
            )),
        ]
        try:
            for context in patches:
                context.__enter__()
            report = run_agent_team(
                {}, emit=completed_events.append, emit_progress=progress_events.append
            )
        finally:
            for context in reversed(patches):
                context.__exit__(None, None, None)

        self.assertEqual(report["status"], "ready_for_human_review")
        self.assertEqual(progress_events[0]["agent"], "settings_agent")
        self.assertEqual(progress_events[0]["status"], "running")
        self.assertEqual(completed_events[0]["agent"], "settings_agent")
        self.assertEqual(completed_events[0]["status"], "ok")
        self.assertTrue(any(
            event["agent"] == "director" and event["status"] == "running"
            for event in progress_events
        ))
        self.assertEqual(len(completed_events), 11)
        self.assertEqual(len(report["events"]), 11)  # Stable completed-results contract.


if __name__ == "__main__":
    unittest.main()
