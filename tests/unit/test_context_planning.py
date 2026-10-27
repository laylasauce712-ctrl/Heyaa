import math
import statistics
import subprocess
import unittest
from unittest.mock import patch

from src import agent_director as renderer
from src.heyaa.agents import settings_agent


class ContextPlanningTests(unittest.TestCase):
    def setUp(self):
        self.old_edit_duration = renderer.EDIT_DURATION
        self.old_beat_sync = renderer.BEAT_SYNC
        self.old_drop_time = renderer.DROP_BEAT_TIME
        self.old_fps = renderer.FPS
        self.old_min_shot_seconds = renderer.MIN_SHOT_SECONDS
        self.old_min_clips = renderer.MIN_CLIPS
        self.old_max_clips = renderer.MAX_CLIPS
        self.old_beat_grid_analysis = dict(renderer.BEAT_GRID_ANALYSIS)

    def tearDown(self):
        renderer.EDIT_DURATION = self.old_edit_duration
        renderer.BEAT_SYNC = self.old_beat_sync
        renderer.DROP_BEAT_TIME = self.old_drop_time
        renderer.FPS = self.old_fps
        renderer.MIN_SHOT_SECONDS = self.old_min_shot_seconds
        renderer.MIN_CLIPS = self.old_min_clips
        renderer.MAX_CLIPS = self.old_max_clips
        renderer.BEAT_GRID_ANALYSIS.clear()
        renderer.BEAT_GRID_ANALYSIS.update(self.old_beat_grid_analysis)

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

    def test_synthetic_130_bpm_pulses_produce_confident_phase_locked_grid(self):
        hop_seconds = 0.02
        expected_period_frames = round(60.0 / 130.0 / hop_seconds)
        envelope = [0.0] * 500
        for frame in range(7, len(envelope), expected_period_frames):
            envelope[frame] = 1.0
            if frame > 0:
                envelope[frame - 1] = 0.2
            if frame + 1 < len(envelope):
                envelope[frame + 1] = 0.1

        period_frames = renderer._estimate_period_frames(envelope)
        self.assertIsNotNone(period_frames)
        estimated_bpm = 60.0 / (period_frames * hop_seconds)
        self.assertAlmostEqual(estimated_bpm, 130.0, delta=8.0)

        grid = renderer._build_beat_grid(envelope, period_frames, hop_seconds, limit=8.0)
        self.assertIsNotNone(grid)
        self.assertGreaterEqual(grid["confidence"], 0.5)
        self.assertAlmostEqual(grid["phase_seconds"], 7 * hop_seconds, delta=hop_seconds)
        intervals = [right - left for left, right in zip(grid["beats"], grid["beats"][1:])]
        self.assertTrue(intervals)
        self.assertTrue(all(abs(interval - expected_period_frames * hop_seconds) < 1e-6
                            for interval in intervals))

        renderer.EDIT_DURATION = 4.0
        renderer.MIN_SHOT_SECONDS = 0.75
        renderer.BEAT_GRID_ANALYSIS.update({
            "method": "period_phase_grid", "period_seconds": grid["period_seconds"]
        })
        boundaries = renderer.make_boundaries(4, grid["beats"], {
            "shot_intervals_seconds": [1.0, 1.0, 1.0, 1.0],
            "median_cut_interval_seconds": 1.0,
        })
        self.assertTrue(any(abs(boundary - beat) < 1e-8
                            for boundary in boundaries[1:-1] for beat in grid["beats"]))

    def test_short_reference_auto_derives_clip_count_to_match_fast_pacing(self):
        renderer.EDIT_DURATION = 17.75
        renderer.MIN_CLIPS = 8
        renderer.MAX_CLIPS = 40
        renderer.MIN_SHOT_SECONDS = 0.75
        profile = {
            "duration_seconds": 11.8,
            "median_cut_interval_seconds": 0.55,
            "shot_intervals_seconds": [0.5, 0.6, 0.5, 0.55, 0.5, 0.6],
        }

        clip_count = renderer.choose_clip_count(0.55)
        self.assertEqual(clip_count, 23)
        boundaries = renderer.make_boundaries(clip_count, [], profile)
        lengths = [right - left for left, right in zip(boundaries, boundaries[1:])]
        self.assertLessEqual(statistics.median(lengths), 0.9)
        self.assertEqual(len(lengths), clip_count)

    def test_settings_agent_accepts_40_clips_and_validates_min_shot_seconds(self):
        cfg = {
            "style": "phonk_montagem",
            "video_settings": {"resolution": "1080x1920", "fps": 24, "codec": "libx264",
                               "crf": 26, "preset": "ultrafast"},
            "edit_settings": {"duration_seconds": 40, "speed": 1.1, "freeze_duration": 2.0,
                              "drop_freeze_duration": 0.25, "edl_mode": "on",
                              "min_clips": 8, "max_clips": 40, "min_shot_seconds": 0.3,
                              "reference_pacing": True, "mirror_enabled": False, "layout_mode": "fill"},
            "audio_settings": {"beat_sync": True, "beat_flash": True, "bass_boost": False,
                               "music_loop": True},
        }
        self.assertEqual(settings_agent(cfg).status, "ok")
        cfg["edit_settings"]["min_shot_seconds"] = 0.29
        self.assertEqual(settings_agent(cfg).status, "blocked")
        cfg["edit_settings"]["min_shot_seconds"] = 3.01
        self.assertEqual(settings_agent(cfg).status, "blocked")
        cfg["edit_settings"]["min_shot_seconds"] = 0.75
        cfg["edit_settings"]["max_clips"] = 41
        self.assertEqual(settings_agent(cfg).status, "blocked")

    def test_scene_feature_parser_reads_astats_rms_and_motion_metadata(self):
        logs = (
            "frame:0 pts:0 pts_time:0.0\\n"
            "lavfi.signalstats.YAVG=3.25\\n"
            "Overall\\nRMS level dB: -12.50\\n"
        )
        with patch(
            "src.agent_director.subprocess.run",
            return_value=subprocess.CompletedProcess(["ffmpeg"], 0, "", logs),
        ):
            measured = renderer.measure_source_scene_features(
                "fixture.mp4", [{"start_seconds": 0.0, "end_seconds": 1.0}]
            )
        self.assertAlmostEqual(measured[0]["audio_loudness_db"], -12.5)
        self.assertAlmostEqual(measured[0]["motion_score"], 3.25)

    def test_ranked_multiscene_assignment_is_chronological_disjoint_and_has_no_forced_shift(self):
        fps = 10
        gap = 1
        segments = [
            {"start_seconds": 0.0, "end_seconds": 3.0, "audio_loudness_db": -18.0, "motion_score": 8.0},
            {"start_seconds": 3.0, "end_seconds": 6.0, "audio_loudness_db": -8.0, "motion_score": 12.0},
            {"start_seconds": 6.0, "end_seconds": 9.0, "audio_loudness_db": -25.0, "motion_score": 4.0},
        ]
        ranked = renderer.rank_source_scene_segments(segments)
        self.assertEqual(
            max(ranked, key=lambda item: item["selection_score"])["start_seconds"], 3.0
        )
        assignments = renderer.plan_ranked_disjoint_source_ranges([8, 8, 8, 8], ranked, fps, gap)
        self.assertEqual(len(assignments), 4)
        self.assertTrue(all(item["forced_shift_frames"] == 0 for item in assignments))
        self.assertEqual(assignments, sorted(assignments, key=lambda item: item["source_start_f"]))
        for left, right in zip(assignments, assignments[1:]):
            self.assertGreaterEqual(
                right["source_start_f"],
                left["source_start_f"] + left["source_dur_f"] + gap,
            )
        self.assertGreaterEqual(len({item["scene_segment_index"] for item in assignments}), 2)
        for item in assignments:
            scene = ranked[item["scene_segment_index"]]
            self.assertGreaterEqual(item["source_start_f"], math.ceil(scene["start_seconds"] * fps) -
                                    (gap if item["scene_segment_index"] == 0 else 0))
            self.assertLessEqual(
                item["source_start_f"] + item["source_dur_f"],
                math.floor(scene["end_seconds"] * fps) +
                (gap if item["scene_segment_index"] == len(ranked) - 1 else 0),
            )

    def test_source_progression_moves_overlapping_candidate_forward_by_minimum_gap(self):
        selected = renderer.enforce_source_progression(
            candidate_start_f=28, source_dur_f=30, previous_source_end_f=30,
            minimum_gap_f=3, maximum_source_start_f=200,
        )
        self.assertEqual(selected, 33)

    def test_source_progression_fails_if_no_non_overlapping_range_remains(self):
        with self.assertRaisesRegex(RuntimeError, "Not enough unused source footage"):
            renderer.enforce_source_progression(
                candidate_start_f=40, source_dur_f=30, previous_source_end_f=100,
                minimum_gap_f=3, maximum_source_start_f=102,
            )

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
