import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.heyaa.release import ReleaseApprovalError, approve_release


def valid_probe():
    return {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1080,
                "height": 1920,
                "avg_frame_rate": "60/1",
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"duration": "22.0"},
    }


class ReleaseApprovalTests(unittest.TestCase):
    def _make_run(self, root: Path, *, inspector_status="ok", final_freeze_frames=120):
        run_dir = root / "output" / "runs" / "run-20261102-001"
        run_dir.mkdir(parents=True)
        video = run_dir / "final_phonk_20s.mp4"
        video.write_bytes(b"fake-mp4-for-probe-test")
        (run_dir / "agent_report.json").write_text(json.dumps({
            "status": "ready_for_human_review",
            "results": {
                "inspector": {"status": inspector_status},
                "export_storage": {"status": "ok"},
            },
        }), encoding="utf-8")
        total_frames = 1200 + final_freeze_frames
        (run_dir / "edit_decision_list.json").write_text(json.dumps({
            "version": 1,
            "fps_num": 60,
            "fps_den": 1,
            "width": 1080,
            "height": 1920,
            "total_frames": total_frames,
            "video": [{
                "type": "clip", "start_f": 0, "dur_f": 1200,
            }, {
                "type": "freeze", "effect": "phonk-freeze",
                "start_f": 1200, "dur_f": final_freeze_frames,
            }],
        }), encoding="utf-8")
        return video, root / "output"

    def test_explicit_approval_copies_verified_render_to_releases_atomically(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video, output_root = self._make_run(root)
            with patch("src.heyaa.release._probe_media", return_value=valid_probe()):
                result = approve_release(video, confirm=True, output_root=output_root)

            self.assertEqual(result["status"], "approved")
            release_dir = Path(result["release_dir"])
            self.assertTrue((release_dir / "final_phonk.mp4").is_file())
            self.assertTrue((release_dir / "agent_report.json").is_file())
            self.assertTrue((release_dir / "edit_decision_list.json").is_file())
            self.assertTrue((release_dir / "release_manifest.json").is_file())
            self.assertEqual(
                (release_dir / "final_phonk.mp4").read_bytes(),
                video.read_bytes(),
            )
            manifest = json.loads((release_dir / "release_manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["user_approved"])
            self.assertEqual(manifest["technical_verification"]["final_freeze_seconds"], 2.0)
            self.assertTrue(video.is_file())  # Approval copies; it does not remove the run artifact.

    def test_approval_requires_explicit_user_confirmation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video, output_root = self._make_run(root)
            with self.assertRaisesRegex(ReleaseApprovalError, "Explicit user approval"):
                approve_release(video, confirm=False, output_root=output_root)
            self.assertFalse((output_root / "releases").exists())

    def test_approval_refuses_report_without_passing_inspector(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video, output_root = self._make_run(root, inspector_status="needs_review")
            with patch("src.heyaa.release._probe_media", return_value=valid_probe()):
                with self.assertRaisesRegex(ReleaseApprovalError, "Inspector"):
                    approve_release(video, confirm=True, output_root=output_root)
            self.assertFalse((output_root / "releases").exists())

    def test_approval_refuses_wrong_final_freeze_duration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video, output_root = self._make_run(root, final_freeze_frames=60)
            with patch("src.heyaa.release._probe_media", return_value=valid_probe()):
                with self.assertRaisesRegex(ReleaseApprovalError, "not the required 2.0 seconds"):
                    approve_release(video, confirm=True, output_root=output_root)
            self.assertFalse((output_root / "releases").exists())

    def test_approval_refuses_media_without_audio(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video, output_root = self._make_run(root)
            probe = valid_probe()
            probe["streams"] = probe["streams"][:1]
            with patch("src.heyaa.release._probe_media", return_value=probe):
                with self.assertRaisesRegex(ReleaseApprovalError, "no audio stream"):
                    approve_release(video, confirm=True, output_root=output_root)
            self.assertFalse((output_root / "releases").exists())

    def test_approval_refuses_paths_outside_the_runs_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "untracked.mp4"
            outside.write_bytes(b"mp4")
            with self.assertRaisesRegex(ReleaseApprovalError, "under output/runs"):
                approve_release(outside, confirm=True, output_root=root / "output")


if __name__ == "__main__":
    unittest.main()
