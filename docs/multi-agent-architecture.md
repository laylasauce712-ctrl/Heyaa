# Heyaa Multi-Agent Architecture (Phonk/Montagem)

## Implemented stages

The current repository runs deterministic Python modules—not an independent LLM swarm. Each stage returns a structured result with status, findings, recommendations and evidence; events in `output/agent_report.json` are emitted from real execution, not fabricated agent chat.

1. **Settings Agent** — validates the actual `params.json` structure, numeric types/ranges, supported codec/preset, clip limits (up to 40), explicit booleans and EDL mode. `edit_settings.min_shot_seconds` defaults to 0.75s and supports 0.3–3.0s; when no exact `--clip-count` is provided, the selected count is derived from measured reference cadence and bounded by the configured limits.
2. **Media Analyst** — reports measured source duration, dimensions, detected scene-change count and music duration. Scene cuts are visual-change heuristics, not semantic scene understanding.
3. **Beat Sync Agent** — estimates a period from the low-frequency onset envelope and phase-locks a beat grid when phase concentration is strong enough; otherwise it retains the previous onset-peak/even-pacing fallback. The report records grid method, period, phase, candidate count and a phase-concentration confidence proxy. This is not guaranteed downbeat/drop detection. When looping is enabled, valid grid candidates repeat at music-cycle offsets.
4. **Reference Analyst** — reports measured median cut pacing only when a usable reference exists. Missing or invalid references lead to default pacing; frames are not copied.
5. **Source Selection** — when the source video has audio, measures each scene interval's RMS loudness via FFmpeg `astats` and low-resolution frame-difference motion, then uses a chronological allocation to choose non-overlapping source windows without post-selection source shifts. Source-time order is retained because the EDL validator requires monotonic ranges. If source audio or feature measurements are unavailable, the legacy scene-center/source-progression fallback remains active.
6. **Framing Agent** — checks crop compatibility and mirroring risks. In `fill` mode, nearby OpenCV appearance-track observations can drive a smoothed piecewise-linear 9:16 crop path; FFmpeg clamps x/y against the scaled-frame bounds. If a continuous track cannot anchor both clip ends, the renderer uses the prior constant-centroid crop or centered crop. `blur_fit` continues to preserve the full source frame over a blurred background. Tracking is a low-confidence position proxy, not semantic identity recognition.
7. **Hook Analyst** — measures opening scene-change count as a pacing proxy. It deliberately returns `insufficient_evidence` for semantic hook strength; scene changes do not reveal what the content means.
8. **Planner / EDL Agent** — validates the EDL schema and frame continuity against actual settings, FPS, dimensions, total frame target, speed, clip-count policy, freeze structure and renderer crop support.
9. **Niche Analyst** — scores craft only when all required normalized metrics are measured. The current pipeline can derive a limited beat-alignment proxy; visual clarity, semantic hook strength, drop impact and motion energy are not fully measured, so a full score remains `insufficient_evidence`. No virality or view-count prediction is made.
10. **Inspector** — verifies output dimensions, configured FPS, codec mapping, exact decoded frame count, duration, audio stream, file presence and full-file decoding. Structural checks do not establish that the edit looks good.
11. **Render Critic** — analyzes FFmpeg black intervals and audio volume. Silent/near-silent output is rejected; long black intervals, very low average level and peaks near 0 dBFS produce a human-review warning. Missing or insufficient critique evidence blocks export. This stage does not judge composition or subject visibility.
12. **Director** — consolidates actual results and records `allow_technical_export` or `block_export`, with explicit blockers and evidence gaps. Settings/Planner/Inspector failures, unsupported framing, and missing, insufficient, malformed or rejecting Critic results prevent promotion. Measured `needs_review` warnings can continue to human review.
13. **Export Storage** — on an authorized decision, atomically promotes the verified temporary file. On a blocked decision, records a blocked event without replacing the previous final output.

## Not implemented yet

- No independent LLM agents, online trend research agent, semantic vision-model reviewer, identity/action recognition, frontend/Agent Room, publish agent or autonomous publishing. Live progress is currently exposed through terminal events plus an append-only `progress.jsonl` trace; this is telemetry for a future interface, not a GUI or independent LLM conversation.
- Real-ESRGAN AI restoration is controlled by `video_settings.ai_upscale_enabled`; it runs only when enabled. In `fill` layout, frames are cropped to 9:16 before restoration and extracted at the source video's nominal frame rate, then resampled to output FPS during composition. `blur_fit` deliberately retains full frames for its blurred background effect. The per-batch timeout is configurable with `video_settings.ai_upscale_batch_timeout_seconds` (30–1800 seconds; default 600). The executable and weights must be installed separately or the renderer fails fast. The model may synthesize plausible texture and cannot guarantee source-truth detail. It does not recognize the person or action in the footage. The renderer has an optional OpenCV HOG appearance-track proxy for framing/cut selection; it can be absent if OpenCV is not installed and cannot identify a real person.
- To enable that lightweight local detector, install `requirements-vision.txt` in the same Python environment used for rendering. For an existing Linux/WSL worktree, `bash scripts/prepare_local_worktree.sh --disable-ai-upscale ../Heyaa-ai-upscale-run` can safely reuse the source worktree's untracked `input/`, local `params.json`, and Real-ESRGAN install, then install OpenCV into an isolated `.venv`. The optional `--disable-ai-upscale` flag disables Real-ESRGAN only in the destination worktree for a faster diagnostic render; omit it when deliberately testing AI restoration. The helper preflights Python venv support and all existing link targets before changing local paths, refuses to overwrite an unrelated `params.local.json`, and leaves tracked `params.json` unchanged. It writes the requested settings to ignored `params.local.json`; start the diagnostic render with `HEYAA_PARAMS_PATH=params.local.json .venv/bin/python src/agent_director.py --variants 1 --clip-count 8`. The helper never modifies the source worktree and expects `input/test_video.mp4` plus `input/phonk.mp3`; a reference video is optional. HOG may still miss small or distant football players, so a missing/stable track remains explicitly reported as a fallback rather than semantic subject understanding.
- No semantic hook score or complete aesthetic craft score. Technical metrics cannot determine whether framing, timing or style feels right for a human viewer.
- No automatic retry loop yet. A failed technical gate blocks promotion and records findings for diagnosis.
- EDL v1 supports one audio segment spanning the full timeline and the full-source crop rectangle; unsupported schedules/rectangles fail fast.
- Termux render performance has not been benchmarked on the user's Android device.

## Live progress and clip-count comparisons

Each render writes `output/progress.jsonl` (or `output/variants/variant_NN/progress.jsonl` for comparison renders). Each JSONL row has a UTC timestamp, stage, status, summary and structured details. It records source/settings preflight, analysis, selected clip count, per-clip render completion, EDL validation, Inspector, the structured agent results, Director decision and Export Storage result. The terminal remains the live stream; `progress.jsonl` is the durable machine-readable trace. The existing `agent_report.json`, `pre_render_review.json` and `edit_decision_list.json` remain in place.

The renderer can compare exact motion-clip counts while retaining the same selected source, music, edit style and configured effects. The `--clip-count-options` parser accepts counts from 6 through 40, matching `edit_settings.max_clips`; it does not impose a separate 18-clip ceiling. In count-comparison mode, source-time progression is held to the same balanced profile so the primary planned difference is the number of clips. For the configured 8–40 clip bounds, use:

```bash
python3 src/agent_director.py --variants 3 --clip-count-options 8,12,16

Each invocation stores artifacts in `output/runs/<timestamp>/`; `output/latest` points to the latest completed run. A `contact_sheet.png` is generated after successful rendering. Use `python3 src/agent_director.py --preview` for a one-pass 540x960, 30fps preview with AI upscaling disabled, and `python3 src/agent_director.py doctor` to check FFmpeg/FFprobe, SVG overlay support, OpenCV, Real-ESRGAN/Vulkan paths, and free disk. The legacy `output/final_phonk_20s.mp4` remains as a compatibility copy for full renders.
```

The CLI validates every requested count against `params.json` before downloading source media. The resulting videos and their chosen counts are listed in `output/variants/index.json`; inspect `variant_01/final_phonk.mp4`, `variant_02/final_phonk.mp4` and `variant_03/final_phonk.mp4` to choose the pacing you prefer. To render one exact count only, use `--variants 1 --clip-count 12` (the value must remain within `min_clips` and `max_clips`). If the measured reference median is 0.55s, the 20-second profile with a 2-second final freeze selects 24 motion clips at the default 0.75s minimum-shot setting; this is a planning estimate, not proof of real-footage visual quality. Set `edit_settings.min_shot_seconds` lower (down to 0.3s) for faster cuts, provided the configured duration and minimum clip count can satisfy that constraint.

## Audio headroom and soundtrack looping

The final AAC stream is measured after encoding. The output limiter is set to a conservative 0.65 linear ceiling (subject to encoded true-peak remeasurement), and short soundtracks are repeated with a 100ms triangular crossfade when looping is enabled. The run report records whether music was shorter than the full edit, how many cycles were joined and the overlap duration. If looping is disabled, a shorter soundtrack triggers a warning because the remainder is padded to the edit duration.

## Ending freeze effect

The ending skull is original in-repository SVG vector artwork with transparent background; it was authored for Heyaa and no external image asset or attribution dependency is used. The renderer animates its scale during the initial pop-in. Tune `edit_settings.skull_size_px` (160–960), normalized `skull_position_x` / `skull_position_y` (0–1), `skull_pop_seconds` (0.08–0.6s), or disable the procedural low-frequency impact using `impact_sfx_enabled: false`. The SFX is generated from FFmpeg's `aevalsrc`; no external sound file is downloaded. CI checks that a synthetic overlay changes center-region pixels, not that the effect looks good on real footage.

## Workflow and safeguards

```text
params.json
   -> Settings Agent
   -> source/scene analysis + beat candidate analysis
   -> Director builds integer-frame EDL
   -> Planner validates EDL against settings
   -> FFmpeg renders to a temporary path
   -> Inspector verifies the output file
   -> Render Critic measures black/audio risks
   -> Director records allow/block + reasons
   -> if blocked: Export Storage records blocked; preserve previous final
   -> if accepted: Export Storage atomically promotes output/final_phonk_20s.mp4
   -> Niche Analyst reports measured metrics and missing evidence
   -> human visual review (required)
```

The latest CI runs validate the beat-grid helper with synthetic 130 BPM pulses and a synthetic FFmpeg smoke render. Synthetic media does not establish beat-grid accuracy on the user's soundtrack or the visual quality of the real edit. `main` remains untouched; this PR is still a draft.
