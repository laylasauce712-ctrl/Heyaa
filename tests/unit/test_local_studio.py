import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.heyaa import local_app


class LocalStudioSettingsTests(unittest.TestCase):
    def test_save_profile_writes_local_override_without_mutating_tracked_settings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "params.json"
            local = root / "params.local.json"
            original = {
                "style": "phonk_montagem",
                "video_settings": {
                    "resolution": "1080x1920", "fps": 60, "codec": "libx264",
                    "crf": 18, "preset": "veryfast", "ai_upscale_enabled": False,
                    "ai_upscale_model": "realesrgan-x4plus", "ai_upscale_scale": 2,
                    "ai_upscale_binary": "tools/realesrgan/realesrgan-ncnn-vulkan",
                    "ai_upscale_model_dir": "tools/realesrgan/models",
                    "ai_upscale_batch_timeout_seconds": 600, "intermediate_crf": 10,
                },
                "edit_settings": {
                    "duration_seconds": 20, "speed": 1.1, "min_clips": 8, "max_clips": 40,
                    "min_shot_seconds": 0.35, "reference_pacing": True, "mirror_enabled": True,
                    "layout_mode": "blur_fit", "freeze_duration": 2, "drop_freeze_duration": 0.25,
                    "source_min_gap_seconds": 0.05, "source_chapter_seconds": 90,
                    "subject_lock_enabled": True, "edl_mode": "on", "ending_skull_enabled": True,
                    "skull_size_px": 520, "skull_position_x": 0.5, "skull_position_y": 0.5,
                    "skull_pop_seconds": 0.18, "impact_sfx_enabled": True,
                },
                "audio_settings": {
                    "beat_sync": True, "beat_flash": True, "bass_boost": True, "music_loop": True,
                },
            }
            base.write_text(json.dumps(original), encoding="utf-8")
            with (
                patch.object(local_app, "ROOT", root),
                patch.object(local_app, "BASE_SETTINGS", base),
                patch.object(local_app, "LOCAL_SETTINGS", local),
            ):
                result = local_app._save_profile({
                    "edit_settings": {"speed": 1.2, "layout_mode": "fill"},
                    "audio_settings": {"beat_flash": False},
                    "video_settings": {"ai_upscale_enabled": False},
                })

            self.assertTrue(local.is_file())
            self.assertEqual(json.loads(base.read_text(encoding="utf-8")), original)
            saved = json.loads(local.read_text(encoding="utf-8"))
            self.assertEqual(saved["edit_settings"]["speed"], 1.2)
            self.assertEqual(saved["edit_settings"]["layout_mode"], "fill")
            self.assertFalse(saved["audio_settings"]["beat_flash"])
            self.assertFalse(saved["video_settings"]["ai_upscale_enabled"])
            self.assertEqual(result["settings_file"], "params.local.json")

    def test_save_profile_rejects_options_the_renderer_does_not_implement(self):
        with self.assertRaisesRegex(ValueError, "Unsupported edit_settings options"):
            local_app._save_profile({"edit_settings": {"style": "cinematic"}})

    def test_save_profile_rejects_a_non_supported_layout(self):
        with self.assertRaises(ValueError):
            local_app._save_profile({"edit_settings": {"layout_mode": "stretch"}})


class LocalStudioPathSafetyTests(unittest.TestCase):
    def test_quick_preview_is_listed_as_playable_but_never_approvable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runs = root / "output" / "runs"
            run_dir = runs / "run-preview"
            run_dir.mkdir(parents=True)
            preview = run_dir / "preview.mp4"
            preview.write_bytes(b"preview")
            (run_dir / "agent_report.json").write_text(json.dumps({
                "status": "ready_for_human_review",
            }), encoding="utf-8")
            with patch.object(local_app, "RUNS_ROOT", runs):
                outputs = local_app._run_outputs(run_dir)
            self.assertEqual(len(outputs), 1)
            self.assertTrue(outputs[0]["is_preview"])
            self.assertFalse(outputs[0]["can_approve"])
            self.assertEqual(outputs[0]["status"], "preview")

    def test_video_byte_ranges_support_progressive_playback_and_seeking(self):
        self.assertIsNone(local_app._parse_byte_range(None, 100))
        self.assertEqual(local_app._parse_byte_range("bytes=0-9", 100), (0, 9))
        self.assertEqual(local_app._parse_byte_range("bytes=90-", 100), (90, 99))
        self.assertEqual(local_app._parse_byte_range("bytes=-10", 100), (90, 99))
        self.assertEqual(local_app._parse_byte_range("bytes=95-200", 100), (95, 99))

    def test_video_byte_ranges_reject_invalid_or_unsatisfiable_ranges(self):
        for value in ("items=0-5", "bytes=-0", "bytes=100-", "bytes=8-2", "bytes=0-1,4-5"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "byte range"):
                    local_app._parse_byte_range(value, 100)

    def test_upload_slot_aliases_map_to_real_media_kinds(self):
        self.assertEqual(local_app._normalize_upload_slot("source"), "video")
        self.assertEqual(local_app._normalize_upload_slot("video"), "video")
        self.assertEqual(local_app._normalize_upload_slot("music"), "music")
        self.assertEqual(local_app._normalize_upload_slot("reference"), "reference")

    def test_upload_slot_rejects_unknown_kinds(self):
        with self.assertRaisesRegex(ValueError, "Upload slot must be"):
            local_app._normalize_upload_slot("image")

    def test_artifact_route_accepts_files_under_runs_and_releases_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runs = root / "output" / "runs"
            releases = root / "output" / "releases"
            run_video = runs / "run-1" / "final.mp4"
            release_video = releases / "run-1" / "primary" / "final_phonk.mp4"
            run_video.parent.mkdir(parents=True)
            release_video.parent.mkdir(parents=True)
            run_video.write_bytes(b"run")
            release_video.write_bytes(b"release")
            with (
                patch.object(local_app, "ROOT", root),
                patch.object(local_app, "RUNS_ROOT", runs),
                patch.object(local_app, "RELEASES_ROOT", releases),
            ):
                self.assertEqual(
                    local_app._safe_artifact_path("output/runs/run-1/final.mp4"),
                    run_video.resolve(),
                )
                self.assertEqual(
                    local_app._safe_artifact_path("output/releases/run-1/primary/final_phonk.mp4"),
                    release_video.resolve(),
                )

    def test_artifact_route_refuses_files_outside_runs_and_releases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runs = root / "output" / "runs"
            releases = root / "output" / "releases"
            secret = root / "private.txt"
            secret.write_text("not a render", encoding="utf-8")
            with (
                patch.object(local_app, "ROOT", root),
                patch.object(local_app, "RUNS_ROOT", runs),
                patch.object(local_app, "RELEASES_ROOT", releases),
            ):
                with self.assertRaisesRegex(ValueError, "Only render and release artifacts"):
                    local_app._safe_artifact_path("private.txt")

    def test_render_command_contains_existing_engine_options_and_local_input_paths(self):
        config, _ = local_app._load_profile()
        with (
            patch.object(local_app, "_load_profile", return_value=(config, "params.json")),
            patch(
                "src.heyaa.media_sources.validate_input_media_path",
                side_effect=lambda value, kind: f"/project/{value}" if value else "",
            ),
            patch("src.heyaa.media_sources.validate_media_file"),
        ):
            command, summary = local_app._validate_render_request({
                "video_path": "input/source-a.mp4",
                "music_path": "input/beat-a.mp3",
                "reference_path": "",
                "edits": 3,
                "clip_count": 16,
            })
        self.assertIn("--edits", command)
        self.assertEqual(command[command.index("--edits") + 1], "3")
        self.assertEqual(command[command.index("--clip-count") + 1], "16")
        self.assertEqual(command[command.index("--video-path") + 1], "/project/input/source-a.mp4")
        self.assertEqual(command[command.index("--music-path") + 1], "/project/input/beat-a.mp3")
        self.assertEqual(command[command.index("--reference-path") + 1], "")

    def test_render_request_rejects_out_of_range_edit_count_before_launch(self):
        with (
            patch("src.heyaa.media_sources.validate_input_media_path", side_effect=lambda value, kind: f"/project/{value}" if value else ""),
            patch("src.heyaa.media_sources.validate_media_file"),
        ):
            with self.assertRaisesRegex(ValueError, "between 1 and 5 distinct edits"):
                local_app._validate_render_request({"edits": 6})


if __name__ == "__main__":
    unittest.main()
