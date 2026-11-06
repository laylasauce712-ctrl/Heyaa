import subprocess
import unittest

from src.heyaa.creative_profiles import (
    CREATIVE_PROFILE_ORDER, build_motion_filter, get_creative_profile, profile_for_edit,
)


class CreativeProfileTests(unittest.TestCase):
    def test_five_distinct_profiles_are_defined(self):
        self.assertEqual(len(CREATIVE_PROFILE_ORDER), 5)
        self.assertEqual(len({get_creative_profile(name)["motion"] for name in CREATIVE_PROFILE_ORDER}), 5)

    def test_batch_assigns_a_stable_profile_to_each_edit(self):
        self.assertEqual([profile_for_edit(i) for i in range(1, 6)], list(CREATIVE_PROFILE_ORDER))

    def test_profile_filters_are_distinct_and_keep_fixed_output_size(self):
        filters = [build_motion_filter(name, 2, 72, 60, 1080, 1920) for name in CREATIVE_PROFILE_ORDER]
        self.assertEqual(len(set(filters)), 5)
        for value in filters:
            self.assertIn("zoompan=", value)
            self.assertIn("s=1080x1920:fps=60", value)

    def test_unknown_profile_and_invalid_frame_values_are_rejected(self):
        with self.assertRaises(ValueError):
            get_creative_profile("make-it-up")
        with self.assertRaises(ValueError):
            build_motion_filter("cinematic-impact", 0, 0, 60, 1080, 1920)

    def test_synthetic_ffmpeg_accepts_every_profile(self):
        try:
            subprocess.run(["ffmpeg", "-version"], check=True, capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            self.skipTest("FFmpeg is not installed")
        for index, profile_id in enumerate(CREATIVE_PROFILE_ORDER):
            with self.subTest(profile=profile_id):
                filter_chain = build_motion_filter(profile_id, index, 60, 60, 270, 480)
                result = subprocess.run(
                    ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                     "testsrc2=size=270x480:rate=24:duration=1", "-vf", f"fps=60,{filter_chain}",
                     "-frames:v", "60", "-f", "null", "-"],
                    check=False, capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
