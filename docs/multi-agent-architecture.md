# Heyaa Multi-Agent Architecture (Phonk/Montagem)

## Implemented stages

The current repository runs deterministic Python modules—not an independent LLM swarm. Each stage returns a structured result with status, findings, recommendations and evidence; events in `output/agent_report.json` are emitted from real execution, not fabricated agent chat.

1. **Settings Agent** — validates the actual `params.json` structure, numeric types/ranges, supported codec/preset, clip limits, explicit booleans and EDL mode.
2. **Media Analyst** — reports measured source duration, dimensions, detected scene-change count and music duration. Scene cuts are visual-change heuristics, not semantic scene understanding.
3. **Beat Sync Agent** — reports whether beat sync is enabled, how many onset candidates were measured, and whether even-pacing fallback was used. It is a bass-onset/autocorrelation heuristic, not guaranteed downbeat detection. When looping is enabled, valid candidates repeat at music-cycle offsets.
4. **Reference Analyst** — reports measured median cut pacing only when a usable reference exists. Missing or invalid references lead to default pacing; frames are not copied.
5. **Framing Agent** — checks EDL crop compatibility with the current renderer, reports center-crop versus legacy blurred-background mode, and warns that mirroring reverses visible text. Unsupported per-shot crop rectangles block export.
6. **Hook Analyst** — measures opening scene-change count as a pacing proxy. It deliberately returns `insufficient_evidence` for semantic hook strength; scene changes do not reveal what the content means.
7. **Planner / EDL Agent** — validates the EDL schema and frame continuity against actual settings, FPS, dimensions, total frame target, speed, clip-count policy, freeze structure and renderer crop support.
8. **Niche Analyst** — scores craft only when all required normalized metrics are measured. The current pipeline can derive a limited beat-alignment proxy; visual clarity, semantic hook strength, drop impact and motion energy are not fully measured, so a full score remains `insufficient_evidence`. No virality or view-count prediction is made.
9. **Inspector** — verifies output dimensions, configured FPS, codec mapping, exact decoded frame count, duration, audio stream, file presence and full-file decoding. Structural checks do not establish that the edit looks good.
10. **Render Critic** — analyzes FFmpeg black intervals and audio volume. Silent/near-silent output is rejected; long black intervals, very low average level and peaks near 0 dBFS produce a human-review warning. Missing or insufficient critique evidence blocks export. This stage does not judge composition or subject visibility.
11. **Director** — consolidates actual results and records `allow_technical_export` or `block_export`, with explicit blockers and evidence gaps. Settings/Planner/Inspector failures, unsupported framing, and missing, insufficient, malformed or rejecting Critic results prevent promotion. Measured `needs_review` warnings can continue to human review.
12. **Export Storage** — on an authorized decision, atomically promotes the verified temporary file. On a blocked decision, records a blocked event without replacing the previous final output.

## Not implemented yet

- No independent LLM agents, online trend research agent, semantic vision-model reviewer, identity/action recognition, frontend/Agent Room, publish agent or autonomous publishing. Live progress is currently exposed through terminal events plus an append-only `progress.jsonl` trace; this is telemetry for a future interface, not a GUI or independent LLM conversation.
- Real-ESRGAN AI restoration is integrated behind `video_settings.ai_upscale_enabled`; the current Phonk profile sets it to `true`. The executable and weights must be installed separately or the renderer fails fast. A successful run reports which model/scale was used. It may synthesize plausible texture and cannot guarantee source-truth detail. It does not recognize the person or action in the footage. The renderer has an **optional OpenCV HOG appearance-track proxy** for framing/cut selection; it can be absent if OpenCV is not installed and it cannot identify Messi or verify that the same person continues across shots.
- To enable that lightweight local detector in a Python environment, install the optional extra with `python3 -m pip install -r requirements-vision.txt`. This improves person-shaped detection/crop centering where HOG sees the subject; it is not a replacement for semantic video understanding.
- No semantic hook score or complete aesthetic craft score. Technical metrics cannot determine whether framing, timing or style feels right for a human viewer.
- No automatic retry loop yet. A failed technical gate blocks promotion and records findings for diagnosis.
- EDL v1 supports one audio segment spanning the full timeline and the full-source crop rectangle; unsupported schedules/rectangles fail fast.
- Termux render performance has not been benchmarked on the user's Android device.

## Live progress and clip-count comparisons

Each render writes `output/progress.jsonl` (or `output/variants/variant_NN/progress.jsonl` for comparison renders). Each JSONL row has a UTC timestamp, stage, status, summary and structured details. It records source/settings preflight, analysis, selected clip count, per-clip render completion, EDL validation, Inspector, the structured agent results, Director decision and Export Storage result. The terminal remains the live stream; `progress.jsonl` is the durable machine-readable trace. The existing `agent_report.json`, `pre_render_review.json` and `edit_decision_list.json` remain in place.

The renderer can compare exact motion-clip counts while retaining the same selected source, music, edit style and configured effects. In count-comparison mode, source-time progression is held to the same balanced profile so the primary planned difference is the number of clips. For the current 8–16 clip bounds, use:

```bash
python3 src/agent_director.py --variants 3 --clip-count-options 8,12,16
```

The CLI validates every requested count against `params.json` before downloading source media. The resulting videos and their chosen counts are listed in `output/variants/index.json`; inspect `variant_01/final_phonk.mp4`, `variant_02/final_phonk.mp4` and `variant_03/final_phonk.mp4` to choose the pacing you prefer. To render one exact count only, use `--variants 1 --clip-count 12` (the value must remain within `min_clips` and `max_clips`).

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

CI on code commit `d2ab640` passed 41 unit tests and the synthetic end-to-end render test. CI uses generated synthetic media, not the user's actual footage. `main` remains untouched; the PR is a draft targeting `improve/phonk-renderer-v1`, not `main`.
