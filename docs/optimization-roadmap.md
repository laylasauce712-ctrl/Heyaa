# Heyaa optimization roadmap

## Current implemented state (feature branch)

- Output settings are read from `params.json`; supported output is 1080x1920 (9:16), configurable 24–60 FPS, 8–60 seconds, speed 1.0–1.35x, and a frame-quantized final freeze. Unsupported types/ranges fail fast.
- Smart Crop now means a centered aspect-ratio crop to fill the 9:16 frame; it is not face/subject tracking or AI upscaling. Setting `smart_crop: false` selects the legacy blurred-background layout.
- Mirror is an explicit `edit_settings.mirror_enabled` boolean; it no longer alternates on a per-clip rule. A horizontal flip can reverse visible text.
- The validated, frame-based EDL now drives source ranges, clip durations, freeze placement and the supported full-timeline audio segment. The renderer rejects unsupported crop rectangles or unsupported audio schedules instead of silently ignoring them.
- The synthetic CI render checks EDL continuity, exact decoded frame count, output dimensions/FPS/duration, audio and full-file decoding.
- Deterministic Python agents now run real settings, media, beat, reference, framing, opening-scene-change, planning, niche-evidence and render-inspector stages. The Director records an explicit allow/block decision; Export Storage performs atomic promotion only after that decision.
- Missing evidence remains visible. Scene-change counts are not semantic scene understanding; beat timing is a bass-onset/autocorrelation heuristic; the hook agent does not assign semantic hook strength; niche craft scoring remains unavailable until all required metrics are measured.
- The latest CI-confirmed synthetic render before the newest Director/Storage integration passed 32 unit tests and produced an 8-second 1080x1920, 24-FPS file with exactly 192 decoded frames and audio. The current branch CI for the added Director/Storage integration is pending.
- No real user footage has been visually reviewed in this repository's CI.

## Remaining stages

1. **Real-footage visual QA:** test framing, subject visibility, mirrored text, skull scale/position, flash timing, video-to-music impact and audio level using the user's own sample clips.
2. **Critic improvements:** add representative-frame checks, black/frozen-frame detection, audio loudness/clipping checks and bounded retries. Current Inspector rejects structural problems but does not yet analyze aesthetics or run an automatic retry.
3. **Beat timing:** test the full music loop and multiple timebases, quantify confidence and map candidates over a looped soundtrack; keep even pacing on low confidence.
4. **Subject-aware crop:** add optional, tested subject/face detection only when the dependency/model is available; keep deterministic center crop as a clearly labeled fallback.
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
