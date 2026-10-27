import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import agent_director as renderer
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


if __name__ == "__main__":
    unittest.main()
