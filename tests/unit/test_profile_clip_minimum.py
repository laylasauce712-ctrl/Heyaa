import json
import unittest
from pathlib import Path


class DefaultProfileClipMinimumTests(unittest.TestCase):
    def test_default_profile_requires_at_least_eleven_clips(self):
        project_root = Path(__file__).resolve().parents[2]
        profile = json.loads((project_root / "params.json").read_text(encoding="utf-8"))
        edit = profile["edit_settings"]
        self.assertGreaterEqual(edit["min_clips"], 11)
        self.assertLessEqual(edit["min_clips"], edit["max_clips"])
        self.assertLessEqual(edit["max_clips"], 40)
        # GPU binaries and weights are ignored/local assets, not part of a fresh clone.
        self.assertIs(profile["video_settings"]["ai_upscale_enabled"], False)


if __name__ == "__main__":
    unittest.main()
