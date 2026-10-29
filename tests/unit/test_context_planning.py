import math
import statistics
import tempfile
from pathlib import Path
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

    def test_analysis_cache_uses_file_hash_and_parameters(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.bin"
            cache_dir = root / "cache"
            source.write_bytes(b"first content")
            calls = []
            def compute():
                calls.append(len(calls) + 1)
                return {"candidate_count": len(calls)}
            first, first_hit = renderer.cached_analysis(
                "fixture", [source], {"fps": 30}, compute, cache_dir=cache_dir,
            )
            second, second_hit = renderer.cached_analysis(
                "fixture", [source], {"fps": 30}, compute, cache_dir=cache_dir,
            )
            third, third_hit = renderer.cached_analysis(
                "fixture", [source], {"fps": 60}, compute, cache_dir=cache_dir,
            )
            self.assertFalse(first_hit)
            self.assertTrue(second_hit)
            self.assertFalse(third_hit)
            self.assertEqual(first, second)
            self.assertEqual(first["candidate_count"], 1)
            self.assertEqual(third["candidate_count"], 2)

    def test_long_source_selection_uses_full_timeline_while_short_source_keeps_context(self):
        long_scope = renderer.choose_source_selection_scope(
            source_duration=12 * 60.0, target_duration=18.0,
            context_start=260.0, context_end=296.0,
        )
        self.assertEqual(long_scope["method"], "full_source_long_video")
        self.assertEqual(long_scope["start_seconds"], 0.0)
        self.assertEqual(long_scope["end_seconds"], 720.0)

        short_scope = renderer.choose_source_selection_scope(
            source_duration=45.0, target_duration=18.0,
            context_start=5.0, context_end=41.0,
        )
        self.assertEqual(short_scope["method"], "context_window_short_video")
        self.assertEqual(short_scope["start_seconds"], 5.0)
        self.assertEqual(short_scope["end_seconds"], 41.0)

    def test_long_source_candidates_cover_timeline_in_bounded_non_overlapping_windows(self):
        segments = renderer.build_source_scene_segments(
            0.0, 12.0, [5.0], max_segment_seconds=4.0,
        )
        self.assertGreaterEqual(len(segments), 4)
        self.assertAlmostEqual(segments[0]["start_seconds"], 0.0)
        self.assertAlmostEqual(segments[-1]["end_seconds"], 12.0)
        for segment in segments:
            self.assertGreaterEqual(segment["end_seconds"] - segment["start_seconds"], 0.25)
            self.assertLessEqual(segment["end_seconds"] - segment["start_seconds"], 4.0 + 1e-9)
        for left, right in zip(segments, segments[1:]):
            self.assertAlmostEqual(left["end_seconds"], right["start_seconds"])

    def test_invalid_source_scope_and_candidate_window_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "scope"):
            renderer.choose_source_selection_scope(720.0, 18.0, 10.0, 5.0)
        with self.assertRaisesRegex(ValueError, "max_segment_seconds"):
            renderer.build_source_scene_segments(0.0, 10.0, [], max_segment_seconds=0.1)

    def test_scene_detection_scales_down_before_scoring(self):
        filt = renderer.scene_detection_filter(threshold=0.22, width=320)
        self.assertLess(filt.index("scale=320:-2"), filt.index("select="))
        self.assertIn("gt(scene,0.22)", filt)

    def test_music_loop_graph_crossfades_short_soundtrack_and_trims_to_edit(self):
        result = renderer.build_music_loop_graph(
            music_duration=2.5, target_duration=8.0, loop_enabled=True,
            crossfade_seconds=0.1,
        )
        self.assertGreaterEqual(result["loop_count"], 4)
        self.assertEqual(result["output_label"], "looped_music")
        self.assertIn("acrossfade=d=0.100000:c1=tri:c2=tri", result["graph"])
        self.assertIn("atrim=duration=8.000000", result["graph"])

    def test_music_loop_graph_does_not_loop_when_not_needed_or_disabled(self):
        long_music = renderer.build_music_loop_graph(12.0, 8.0, loop_enabled=True)
        disabled = renderer.build_music_loop_graph(2.5, 8.0, loop_enabled=False)
        self.assertEqual(long_music["graph"], "")
        self.assertEqual(long_music["loop_count"], 1)
        self.assertEqual(disabled["output_label"], "1:a:0")
        self.assertEqual(disabled["loop_count"], 1)

    def test_dynamic_crop_path_is_bounded_smoothed_and_piecewise_linear(self):
        observations = []
        for index, center_x in enumerate([0.1, 0.9, 0.1, 0.9, 0.1, 0.9]):
            observations.append({
                "time_seconds": index * 0.2,
                "center_x": center_x,
                "center_y": 1.2 if index % 2 else -0.2,
            })
        path = renderer.build_dynamic_crop_path(
            observations, 0.0, 1.0, max_distance_seconds=0.5, smoothing_tau_seconds=0.65
        )
        self.assertIsNotNone(path)
        points = path["points"]
        self.assertGreaterEqual(len(points), 4)
        self.assertTrue(all(0.0 <= point["x"] <= 1.0 for point in points))
        self.assertTrue(all(0.0 <= point["y"] <= 1.0 for point in points))
        unsmoothed_x = [0.1, 0.9, 0.1, 0.9, 0.1, 0.9]
        raw_max_step = max(abs(right - left) for left, right in zip(unsmoothed_x, unsmoothed_x[1:]))
        smooth_max_step = max(abs(right["x"] - left["x"]) for left, right in zip(points, points[1:]))
        self.assertLess(smooth_max_step, raw_max_step)
        self.assertIn("max(0,min(iw-ow", path["x_expression"])
        self.assertIn("max(0,min(ih-oh", path["y_expression"])
        self.assertIn("if(lt(t,", path["x_expression"])
        self.assertIn("if(lt(t,", path["y_expression"])

    def test_disabling_skull_leaves_final_freeze_overlay_branch_intact(self):
        with patch.object(renderer, "ENDING_SKULL_ENABLED", False):
            graph, output_label = renderer.build_skull_overlay_graph(18.0)
        self.assertEqual(graph, "")
        self.assertEqual(output_label, "[impact_raw]")

        with (patch.object(renderer, "ENDING_SKULL_ENABLED", True),
              patch.object(renderer, "WIDTH", 1080),
              patch.object(renderer, "FPS", 30)):
            graph, output_label = renderer.build_skull_overlay_graph(18.0)
        self.assertIn("[2:v]", graph)
        self.assertIn("[skull]", graph)
        self.assertEqual(output_label, "[impact]")

    def test_motion_clip_filter_pads_to_exact_edl_frame_count(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(renderer, "FPS", 24), \
             patch.object(renderer, "WIDTH", 1080), \
             patch.object(renderer, "HEIGHT", 1920), \
             patch.object(renderer, "SPEED", 1.1), \
             patch.object(renderer, "MIRROR_ENABLED", False), \
             patch.object(renderer, "LAYOUT_MODE", "fill"), \
             patch.object(renderer, "SUBJECT_OBSERVATIONS", []), \
             patch.object(renderer, "AI_UPSCALE_ENABLED", False), \
             patch.object(renderer, "CODEC", "libx264"), \
             patch.object(renderer, "INTERMEDIATE_CRF", 10), \
             patch.object(renderer, "WORK", temporary), \
             patch.object(renderer, "VIDEO", "input/test_video.mp4"), \
             patch.object(renderer, "run") as run_mock:
            item = {
                "source_start_f": 0, "source_dur_f": 26, "dur_f": 24,
                "crop": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
            }
            renderer.make_clip(1, item, source_duration=20.0)
            command = run_mock.call_args.args[0]
        graph = command[command.index("-filter_complex") + 1]
        self.assertEqual(graph.count("tpad=stop_mode=clone:stop=24"), 1)
        self.assertEqual(graph.count("trim=end_frame=24"), 1)

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
