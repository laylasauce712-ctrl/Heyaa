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
    def test_local_settings_path_can_be_selected_without_editing_params_json(self):
        with patch.dict("os.environ", {"HEYAA_PARAMS_PATH": "params.local.json"}):
            self.assertEqual(renderer._settings_path(), "params.local.json")
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(renderer._settings_path(), "params.json")

    def test_drop_boundary_falls_back_instead_of_exceeding_max_shot_length(self):
        boundaries = [0.0, 1.74, 3.48, 5.57, 7.66, 9.40, 11.14, 14.44, 17.74]
        updated, freeze_time = renderer.insert_drop_boundary(boundaries, 10.74)

        # Snapping to 10.74s would make the following shot 3.70s (> 3.3s).
        # Keep the validated boundaries and move the freeze to the nearest cut.
        self.assertEqual(updated, boundaries)
        self.assertAlmostEqual(freeze_time, 11.14)
        durations = [right - left for left, right in zip(updated, updated[1:])]
        self.assertTrue(all(0.75 <= duration <= 3.3 for duration in durations))

    def test_drop_boundary_snaps_when_both_adjacent_shots_remain_bounded(self):
        updated, freeze_time = renderer.insert_drop_boundary([0.0, 2.0, 4.0, 6.0], 3.0)
        self.assertEqual(updated, [0.0, 3.0, 4.0, 6.0])
        self.assertAlmostEqual(freeze_time, 3.0)
        durations = [right - left for left, right in zip(updated, updated[1:])]
        self.assertTrue(all(0.75 <= duration <= 3.3 for duration in durations))

    def test_reference_pacing_reports_when_clip_count_stretches_cadence(self):
        diagnostics = renderer._reference_pacing_diagnostics(
            {
                "median_cut_interval_seconds": 0.55,
                "shot_intervals_seconds": [0.5, 0.6, 0.5, 1.001],
            },
            [1.74, 1.74, 2.09, 2.09, 1.74, 1.74, 3.30, 3.30],
        )
        self.assertIsNotNone(diagnostics)
        self.assertEqual(diagnostics["planned_clip_count"], 8)
        self.assertEqual(diagnostics["reference_median_seconds"], 0.55)
        self.assertGreater(diagnostics["cadence_stretch_ratio"], 3.0)

        self.assertIsNone(renderer._reference_pacing_diagnostics(None, [1.0]))
        self.assertIsNone(renderer._reference_pacing_diagnostics(
            {"median_cut_interval_seconds": 0.0}, [1.0]
        ))

    def test_reference_availability_comes_from_measured_pacing_evidence(self):
        # reference_pacing_profile() returns measured fields; it does not need an
        # additional "available" flag for progress reporting.
        profile = {
            "median_cut_interval_seconds": 0.55,
            "shot_intervals_seconds": [0.5, 0.6, 0.5],
        }
        self.assertTrue(renderer._has_usable_reference_profile(profile))
        self.assertFalse(renderer._has_usable_reference_profile({
            "median_cut_interval_seconds": None,
            "shot_intervals_seconds": [],
        }))
        self.assertFalse(renderer._has_usable_reference_profile(None))

    def test_variant_interrupt_stops_child_and_exits_with_130(self):
        child = unittest.mock.Mock()
        child.pid = 4321
        child.wait.side_effect = [KeyboardInterrupt(), 0]
        child.poll.return_value = None
        events = []

        with (
            patch("src.agent_director.subprocess.Popen", return_value=child) as popen,
            patch("src.agent_director.os.killpg") as killpg,
            patch.object(
                renderer,
                "progress_event",
                side_effect=lambda stage, status, summary, details=None, **kwargs:
                    events.append((stage, status, details or {})),
            ),
        ):
            with self.assertRaises(SystemExit) as raised:
                renderer._run_variant_process(["python", "child.py"], 2)

        self.assertEqual(raised.exception.code, 130)
        popen.assert_called_once()
        self.assertEqual(popen.call_args.kwargs, {"start_new_session": True})
        killpg.assert_called_once_with(4321, renderer.signal.SIGINT)
        self.assertEqual([(stage, status) for stage, status, _ in events], [
            ("variant_interrupt", "running"),
            ("variant_interrupt", "cancelled"),
        ])

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

    def test_ai_upscaling_timeout_emits_error_and_fails_clearly(self):
        events = []
        with tempfile.TemporaryDirectory() as temporary:
            def fake_run(command, **kwargs):
                if command[0] == "ffmpeg":
                    pattern = Path(command[-1])
                    for frame in range(1, 3):
                        Path(str(pattern).replace("%08d", f"{frame:08d}")).write_bytes(b"fake-png")
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
                self.assertEqual(kwargs.get("timeout"), 600)
                raise subprocess.TimeoutExpired(command, timeout=600)

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
                with self.assertRaisesRegex(RuntimeError, "timed out after 600 seconds"):
                    renderer.prepare_ai_upscaled_frames(0, 0.0, 1.0, 2)

            self.assertEqual([(stage, status) for stage, status, _, _ in events], [
                ("upscale_extract", "running"),
                ("upscale_extract", "completed"),
                ("upscale_batch", "running"),
                ("upscale_batch", "error"),
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
