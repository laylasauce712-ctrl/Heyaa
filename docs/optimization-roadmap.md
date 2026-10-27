# Heyaa optimization roadmap

## Current implemented state (feature branch)

- Output settings are read from `params.json`; supported output is 1080x1920 (9:16), configurable 24–60 FPS, 8–60 seconds, speed 1.0–1.35x, and a frame-quantized final freeze. Unsupported types/ranges fail fast.
- Smart Crop fills the 9:16 frame with a centered fallback. If optional OpenCV is installed and its built-in HOG detector finds a recurring person-shaped appearance track in the selected context window, nearby observations guide source timing and crop center. This is a low-confidence appearance-consistency proxy, not face recognition or semantic identification of who is protecting/following whom. The planner also selects a contiguous source-time context window based on moderate scene-cut density rather than sampling evenly across an entire long recording. Setting `smart_crop: false` selects the legacy blurred-background layout.
- Mirror is an explicit `edit_settings.mirror_enabled` boolean; it no longer alternates on a per-clip rule. A horizontal flip can reverse visible text.
- The validated, frame-based EDL now drives source ranges, clip durations, freeze placement and the supported full-timeline audio segment. The renderer rejects unsupported crop rectangles or unsupported audio schedules instead of silently ignoring them.
- The synthetic CI render checks EDL continuity, exact decoded frame count, output dimensions/FPS/duration, audio and full-file decoding.
- Deterministic Python agents run real settings, media, beat, reference, framing, opening-scene-change, planning, niche-evidence, Inspector and Render Critic stages. Hook Analyst supplies an opening cut-cadence proxy, and Niche Analyst supplies a low-confidence craft proxy composite only when required inputs exist; neither claims semantic hook understanding or predicts virality. A structured evidence-linked review conference is stored in the report and printed in the terminal; it is rule-based cross-review, not independent LLM-to-LLM conversation.
- The final skull freeze is configured to 1.7–3.0 seconds. When a sufficiently strong bass-onset proxy is detected, the EDL may include a short internal drop-impact hold (black-and-white with a brief shake) followed by continued footage, while retaining the final Phonk freeze. The final freeze uses the custom skull SVG icon at a larger scale.
- Missing evidence remains visible. Scene-change counts are not semantic scene understanding; beat timing is a bass-onset/autocorrelation heuristic; the hook agent does not assign semantic hook strength; niche craft scoring remains unavailable until all required metrics are measured.
- CI on code commit d2ab640 passed 41 unit tests and the synthetic render, including measured Render Critic output, the explicit Director decision, Export Storage operation, and an 8-second 1080x1920, 24-FPS output with exactly 192 decoded frames and audio.
- No real user footage has been visually reviewed in this repository's CI.

## Remaining stages

1. **Real-footage visual QA:** test framing, subject visibility, mirrored text, skull scale/position, flash timing, drop-freeze placement, and audio level using the user's own sample clips.
2. **Critic improvements:** add representative-frame checks, frozen-frame detection and bounded retries. Current Render Critic measures black intervals and audio volume risk, but does not analyze aesthetics or run an automatic retry.
3. **Beat timing:** test the full music loop and multiple timebases, quantify confidence and map candidates over a looped soundtrack; keep even pacing on low confidence.
4. **Stronger semantic subject tracking:** evaluate track consistency across camera cuts and multiple visible people, add tests on representative footage, and optionally add a vision-language step to distinguish the target person/action and its narrative role. Current HOG tracking is opportunistic and must not be described as reliable identity tracking.
5. **Agent Room/UI:** wire real structured events to an actual UI if/when the frontend exists. The current repository contains no frontend, so it cannot display a live Agent Room yet.
6. **True LLM collaboration and trend research:** add explicit providers, prompts, cost/timeout controls and evidence citations before describing the system as independent AI agents. Do not fabricate inter-agent chat or promise virality.
7. **Termux performance:** benchmark render time, memory and storage on a real Android device before claiming performance optimization.

## Acceptance gates

- Unit tests and the synthetic FFmpeg smoke test pass on the current branch head.
- One validated settings object feeds settings QA, EDL planning and FFmpeg rendering without silent clamping.
- Unsupported timeline/crop/audio combinations block export before expensive rendering.
- The Director reports its decision, evidence and blockers; Export Storage does not replace the last known-good file unless all required technical gates pass.
- A real-footage review is recorded separately from synthetic CI evidence.
- Do not merge to `main` until the project owner reviews the evidence and explicitly approves.
