import unittest

from src import agent_director as renderer


class ContextPlanningTests(unittest.TestCase):
    def setUp(self):
        self.old_edit_duration = renderer.EDIT_DURATION
        self.old_beat_sync = renderer.BEAT_SYNC
        self.old_drop_time = renderer.DROP_BEAT_TIME
        self.old_fps = renderer.FPS

    def tearDown(self):
        renderer.EDIT_DURATION = self.old_edit_duration
        renderer.BEAT_SYNC = self.old_beat_sync
        renderer.DROP_BEAT_TIME = self.old_drop_time
        renderer.FPS = self.old_fps

    def test_reference_profile_generates_non_uniform_bounded_shot_lengths(self):
        renderer.EDIT_DURATION = 16.0
        profile = {
            "shot_intervals_seconds": [0.8, 2.7, 0.9, 2.4, 1.0, 2.8, 1.1, 1.9],
        }
        boundaries = renderer._reference_boundaries(8, renderer.EDIT_DURATION, profile)
        lengths = [b - a for a, b in zip(boundaries, boundaries[1:])]
        self.assertEqual(len(boundaries), 9)
        self.assertAlmostEqual(boundaries[0], 0.0)
        self.assertAlmostEqual(boundaries[-1], 16.0)
        self.assertGreater(max(lengths) - min(lengths), 0.5)
        self.assertGreaterEqual(min(lengths), 0.75)
        self.assertLessEqual(max(lengths), 3.3)

    def test_invalid_reference_cut_timestamps_fall_back_to_variable_interval_pattern(self):
        renderer.EDIT_DURATION = 16.0
        profile = {
            "duration_seconds": 10.0,
            # These cuts create one oversized gap after scaling to 16s, so the
            # exact-timestamp path must reject them and use measured shot intervals.
            "cut_timestamps_seconds": [1.0, 1.1, 1.2, 1.3, 1.4, 6.5, 8.0],
            "shot_intervals_seconds": [0.8, 2.7, 0.9, 2.4, 1.0, 2.8, 1.1, 1.9],
        }
        boundaries = renderer._reference_boundaries(8, renderer.EDIT_DURATION, profile)
        lengths = [b - a for a, b in zip(boundaries, boundaries[1:])]
        self.assertFalse(renderer.REFERENCE_CUT_TIMESTAMPS_USED)
        self.assertAlmostEqual(sum(lengths), 16.0)
        self.assertGreater(max(lengths) - min(lengths), 0.5)
        self.assertGreaterEqual(min(lengths), 0.75)
        self.assertLessEqual(max(lengths), 3.3)

    def test_extreme_reference_intervals_are_constrained_without_losing_total_duration(self):
        renderer.EDIT_DURATION = 16.0
        profile = {
            "shot_intervals_seconds": [0.25, 0.26, 0.27, 0.29, 3.9, 3.8, 3.7, 3.6],
        }
        boundaries = renderer._reference_boundaries(8, renderer.EDIT_DURATION, profile)
        lengths = [b - a for a, b in zip(boundaries, boundaries[1:])]
        self.assertAlmostEqual(boundaries[0], 0.0)
        self.assertAlmostEqual(boundaries[-1], 16.0)
        self.assertAlmostEqual(sum(lengths), 16.0)
        self.assertGreaterEqual(min(lengths), 0.75)
        self.assertLessEqual(max(lengths), 3.3)
        self.assertGreater(max(lengths) - min(lengths), 0.5)

    def test_music_beat_snap_does_not_break_reference_boundaries(self):
        renderer.EDIT_DURATION = 16.0
        profile = {
            "shot_intervals_seconds": [0.8, 2.7, 0.9, 2.4, 1.0, 2.8, 1.1, 1.9],
        }
        beats = [2.1, 4.4, 6.1, 8.8, 11.3, 13.2]
        boundaries = renderer.make_boundaries(8, beats, profile)
        lengths = [b - a for a, b in zip(boundaries, boundaries[1:])]
        self.assertEqual(len(boundaries), 9)
        self.assertAlmostEqual(boundaries[-1], renderer.EDIT_DURATION)
        self.assertGreaterEqual(min(lengths), 0.75)
        self.assertLessEqual(max(lengths), 3.3)

    def test_long_source_selects_one_moderately_active_contiguous_context(self):
        cuts = [20.0, 100.0]
        cuts.extend(100.0 + 2.5 * i for i in range(1, 16))
        cuts.extend([300.0, 500.0])
        result = renderer.choose_context_window(600.0, cuts, 20.0)
        self.assertAlmostEqual(result["window_seconds"], 40.0)
        self.assertGreaterEqual(result["scene_cuts"], 14)
        self.assertLessEqual(result["scene_cuts"], 18)
        self.assertEqual(result["method"], "moderate-scene-cut-density-window")
        self.assertFalse(result["same_person_tracking"])

    def test_drop_proxy_chooses_a_valid_occurrence_in_the_music_loop(self):
        renderer.BEAT_SYNC = True
        renderer.DROP_BEAT_TIME = 4.2
        result = renderer.choose_drop_beat(9.0, 18.3, True)
        self.assertAlmostEqual(result, 4.2)

    def test_pre_render_review_reports_freezes_reference_and_pending_qa(self):
        renderer.FPS = 24
        edl = {
            "total_frames": 192,
            "video": [
                {"type": "clip", "start_f": 0, "dur_f": 73},
                {"type": "freeze", "start_f": 73, "dur_f": 6, "effect": "drop-impact-freeze"},
                {"type": "clip", "start_f": 79, "dur_f": 72},
                {"type": "freeze", "start_f": 151, "dur_f": 41, "effect": "phonk-freeze"},
            ],
        }
        profile = {"median_cut_interval_seconds": 1.2,
                   "shot_intervals_seconds": [0.8, 1.7, 1.1]}
        context = {"start_seconds": 100.0, "end_seconds": 140.0,
                   "subject_tracking": {"detected": True, "track_span_seconds": 8.0}}
        subject = {"detected": True, "track_span_seconds": 8.0, "track_quality_proxy": 0.65}
        review = renderer.build_pre_render_review(edl, 12, 4.2, 0.25, profile, context, subject)
        self.assertEqual(len(review), 4)
        self.assertIn("0.250s internal hold", review[0]["message"])
        self.assertIn("shot intervals", review[1]["message"])
        self.assertIn("OpenCV found", review[2]["message"])
        self.assertEqual(review[3]["evidence"]["decision"], "pending_render_qa")
        self.assertAlmostEqual(review[3]["evidence"]["final_freeze_duration_seconds"], 41 / 24)

    def test_internal_freeze_boundary_is_inserted_without_changing_clip_count(self):
        boundaries = [0.0, 2.0, 4.0, 6.0, 8.0]
        updated, position = renderer.insert_drop_boundary(boundaries, 4.1)
        self.assertEqual(len(updated), len(boundaries))
        self.assertIn(position, updated)
        self.assertAlmostEqual(position, 4.1)
        self.assertEqual(updated[0], 0.0)
        self.assertEqual(updated[-1], 8.0)


if __name__ == "__main__":
    unittest.main()
