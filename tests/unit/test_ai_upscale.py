import contextlib
import io
import json
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

    def test_ai_extraction_command_crops_before_upscale_at_source_frame_rate(self):
        command = renderer.build_ai_frame_extract_command(
            "input/video.mp4", 1.0, 2.0, 60, 30.0, "/tmp/frame_%08d.png",
            pre_upscale_crop_filter="crop=w='if(gte(iw/ih,0.5625),ih*0.5625,iw)':h=ih:x=0:y=0",
        )
        vf = command[command.index("-vf") + 1]
        self.assertLess(vf.index("crop="), vf.index("fps=30.000000"))
        self.assertEqual(command[command.index("-frames:v") + 1], "60")
        self.assertEqual(command[command.index("-t") + 1], f"{2.0 + 1.0 / 30.0:.6f}")

    def test_intermediate_crf_is_validated_for_near_lossless_clips(self):
        cfg = valid_config()
        cfg["video_settings"]["intermediate_crf"] = 10
        self.assertEqual(settings_agent(cfg).status, "ok")
        cfg["video_settings"]["intermediate_crf"] = 25
        self.assertEqual(settings_agent(cfg).status, "blocked")

    def test_ai_upscale_timeout_setting_accepts_configured_bounds(self):
        cfg = valid_config()
        cfg["video_settings"]["ai_upscale_batch_timeout_seconds"] = 900
        self.assertEqual(settings_agent(cfg).status, "ok")
        cfg["video_settings"]["ai_upscale_batch_timeout_seconds"] = 10
        self.assertEqual(settings_agent(cfg).status, "blocked")

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

            def fake_run(command, check=False, capture_output=False, text=False, timeout=None):
                if command[0] == "ffmpeg":
                    pattern = Path(command[-1])
                    for frame in range(1, 4):
                        (pattern.parent / f"frame_{frame:08d}.png").write_bytes(b"input-frame")
                else:
                    self.assertEqual(timeout, 600)
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

    def test_missing_upscaler_is_checked_before_source_download(self):
        with patch("src.agent_director.load_settings"), \
             patch("src.agent_director.resolve_ai_upscaler", side_effect=FileNotFoundError("missing model")), \
             patch("src.agent_director.prepare_media_sources") as prepare_sources:
            with self.assertRaisesRegex(FileNotFoundError, "missing model"):
                renderer.main(["--variants", "1"])
        prepare_sources.assert_not_called()


    def test_doctor_requires_selected_model_weights_and_executable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            executable = root / "realesrgan-ncnn-vulkan"
            executable.write_text("#!/bin/sh\\nexit 0\\n", encoding="utf-8")
            executable.chmod(0o755)
            models = root / "models"
            models.mkdir()
            settings = root / "params.json"
            settings.write_text(json.dumps({
                "video_settings": {
                    "ai_upscale_enabled": True,
                    "ai_upscale_binary": str(executable),
                    "ai_upscale_model_dir": str(models),
                    "ai_upscale_model": "realesrgan-x4plus",
                    "ai_upscale_scale": 2,
                }
            }), encoding="utf-8")

            with patch("src.agent_director._settings_path", return_value=str(settings)), \\
                 patch("src.agent_director.shutil.which", side_effect=lambda name: f"/usr/bin/{name}"), \\
                 patch("src.agent_director.subprocess.run",
                       return_value=subprocess.CompletedProcess([], 0, "", "")):
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    status_without_weights = renderer.run_doctor()
                report = json.loads(output.getvalue())

                self.assertEqual(status_without_weights, 1)
                self.assertEqual(report["status"], "fail")
                self.assertFalse(report["checks"]["vulkan_realesrgan"]["model_files_exist"])
                self.assertEqual(
                    len(report["checks"]["vulkan_realesrgan"]["missing_model_files"]), 2
                )

                (models / "realesrgan-x4plus.param").write_text("param", encoding="utf-8")
                (models / "realesrgan-x4plus.bin").write_bytes(b"weights")
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    status_with_weights = renderer.run_doctor()
                good_report = json.loads(output.getvalue())

                self.assertEqual(status_with_weights, 0)
                self.assertEqual(good_report["status"], "ok")
                self.assertTrue(good_report["checks"]["vulkan_realesrgan"]["binary_executable"])
                self.assertTrue(good_report["checks"]["vulkan_realesrgan"]["model_files_exist"])

    def test_disabled_mode_does_not_require_real_esrgan_binary(self):
        renderer.AI_UPSCALE_ENABLED = False
        renderer.AI_UPSCALER_EXECUTABLE = "stale-value"
        self.assertIsNone(renderer.resolve_ai_upscaler())
        self.assertIsNone(renderer.AI_UPSCALER_EXECUTABLE)


if __name__ == "__main__":
    unittest.main()
