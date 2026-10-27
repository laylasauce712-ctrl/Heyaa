import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import agent_director as renderer
from src.heyaa.agents import settings_agent


def valid_config():
    return {
        "style": "phonk_montagem",
        "video_settings": {
            "resolution": "1080x1920", "fps": 24, "codec": "libx264",
            "crf": 26, "preset": "ultrafast", "ai_upscale_enabled": True,
            "ai_upscale_model": "realesrgan-x4plus", "ai_upscale_scale": 2,
            "ai_upscale_binary": "tools/realesrgan/realesrgan-ncnn-vulkan",
            "ai_upscale_model_dir": "tools/realesrgan/models",
        },
        "edit_settings": {
            "duration_seconds": 8, "speed": 1.1, "freeze_duration": 2.0,
            "drop_freeze_duration": 0.25, "edl_mode": "on",
            "min_clips": 6, "max_clips": 6, "reference_pacing": False,
            "mirror_enabled": False, "smart_crop": True,
        },
        "audio_settings": {
            "beat_sync": False, "beat_flash": False, "bass_boost": False,
            "music_loop": True,
        },
    }


class AIUpscaleTests(unittest.TestCase):
    def setUp(self):
        self.old = {
            "work": renderer.WORK,
            "fps": renderer.FPS,
            "video": renderer.VIDEO,
            "enabled": renderer.AI_UPSCALE_ENABLED,
            "binary": renderer.AI_UPSCALE_BINARY,
            "model": renderer.AI_UPSCALE_MODEL,
            "scale": renderer.AI_UPSCALE_SCALE,
            "model_dir": renderer.AI_UPSCALE_MODEL_DIR,
            "executable": renderer.AI_UPSCALER_EXECUTABLE,
            "resolved_model_dir": renderer.AI_UPSCALER_MODEL_DIR,
        }

    def tearDown(self):
        renderer.WORK = self.old["work"]
        renderer.FPS = self.old["fps"]
        renderer.VIDEO = self.old["video"]
        renderer.AI_UPSCALE_ENABLED = self.old["enabled"]
        renderer.AI_UPSCALE_BINARY = self.old["binary"]
        renderer.AI_UPSCALE_MODEL = self.old["model"]
        renderer.AI_UPSCALE_SCALE = self.old["scale"]
        renderer.AI_UPSCALE_MODEL_DIR = self.old["model_dir"]
        renderer.AI_UPSCALER_EXECUTABLE = self.old["executable"]
        renderer.AI_UPSCALER_MODEL_DIR = self.old["resolved_model_dir"]

    def test_settings_agent_accepts_explicit_real_esrgan_options(self):
        result = settings_agent(valid_config())
        self.assertEqual(result.status, "ok")
        self.assertTrue(result.evidence["ai_upscale_enabled"])
        self.assertEqual(result.evidence["ai_upscale_model"], "realesrgan-x4plus")
        self.assertEqual(result.evidence["ai_upscale_scale"], 2)

    def test_settings_agent_rejects_unknown_ai_model_and_invalid_scale(self):
        config = valid_config()
        config["video_settings"]["ai_upscale_model"] = "hallucinate-x99"
        config["video_settings"]["ai_upscale_scale"] = True
        result = settings_agent(config)
        self.assertEqual(result.status, "blocked")
        self.assertTrue(any("ai_upscale_model" in finding for finding in result.findings))
        self.assertTrue(any("ai_upscale_scale" in finding for finding in result.findings))

    def test_command_uses_explicit_model_scale_and_model_directory(self):
        command = renderer.build_ai_upscale_command(
            "/opt/realesrgan/realesrgan-ncnn-vulkan",
            "/tmp/input_frames", "/tmp/upscaled_frames",
            "realesrgan-x4plus", 2, "/opt/realesrgan/models",
        )
        self.assertEqual(command, [
            "/opt/realesrgan/realesrgan-ncnn-vulkan",
            "-i", "/tmp/input_frames", "-o", "/tmp/upscaled_frames",
            "-n", "realesrgan-x4plus", "-s", "2",
            "-m", "/opt/realesrgan/models", "-f", "png",
        ])

    def test_enabled_ai_upscale_fails_fast_when_executable_is_missing(self):
        renderer.AI_UPSCALE_ENABLED = True
        renderer.AI_UPSCALE_BINARY = "not-a-real-esrgan-binary-for-test"
        with patch("src.agent_director.shutil.which", return_value=None):
            with self.assertRaisesRegex(FileNotFoundError, "AI upscaling is enabled"):
                renderer.resolve_ai_upscaler()

    def test_enabled_upscale_fails_fast_when_selected_model_weights_are_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / "realesrgan-ncnn-vulkan"
            executable.write_text("#!/bin/sh\\nexit 0\\n", encoding="utf-8")
            executable.chmod(0o755)
            empty_models = Path(temp) / "models"
            empty_models.mkdir()
            renderer.AI_UPSCALE_ENABLED = True
            renderer.AI_UPSCALE_BINARY = str(executable)
            renderer.AI_UPSCALE_MODEL_DIR = str(empty_models)
            renderer.AI_UPSCALE_MODEL = "realesrgan-x4plus"
            with self.assertRaisesRegex(FileNotFoundError, "model files are missing"):
                renderer.resolve_ai_upscaler()

    def test_frame_extraction_and_upscaler_output_are_count_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            renderer.WORK = temp
            renderer.FPS = 2
            renderer.VIDEO = "fixture.mp4"
            renderer.AI_UPSCALE_ENABLED = True
            renderer.AI_UPSCALER_EXECUTABLE = "fake-realesrgan"
            renderer.AI_UPSCALER_MODEL_DIR = str(Path(temp) / "models")
            renderer.AI_UPSCALE_MODEL = "realesrgan-x4plus"
            renderer.AI_UPSCALE_SCALE = 2

            def fake_run(command, check=False, capture_output=False, text=False):
                if command[0] == "ffmpeg":
                    pattern = Path(command[-1])
                    for frame in range(1, 4):
                        (pattern.parent / f"frame_{frame:08d}.png").write_bytes(b"input-frame")
                else:
                    input_dir = Path(command[command.index("-i") + 1])
                    output_dir = Path(command[command.index("-o") + 1])
                    for item in sorted(input_dir.glob("frame_*.png")):
                        (output_dir / item.name).write_bytes(b"upscaled-frame")
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch("src.agent_director.subprocess.run", side_effect=fake_run):
                pattern, root = renderer.prepare_ai_upscaled_frames(1, 1.0, 1.5, 3)

            self.assertEqual(pattern.name, "frame_%08d.png")
            self.assertEqual(len(list((root / "input").glob("frame_*.png"))), 3)
            self.assertEqual(len(list((root / "upscaled").glob("frame_*.png"))), 3)

    def test_disabled_mode_does_not_require_real_esrgan_binary(self):
        renderer.AI_UPSCALE_ENABLED = False
        renderer.AI_UPSCALER_EXECUTABLE = "stale-value"
        self.assertIsNone(renderer.resolve_ai_upscaler())
        self.assertIsNone(renderer.AI_UPSCALER_EXECUTABLE)


if __name__ == "__main__":
    unittest.main()
