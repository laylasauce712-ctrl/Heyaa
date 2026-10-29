# Heyaa optimization roadmap

## Current implemented state (feature branch)

- Output settings are read from `params.json`; supported output is 1080x1920 (9:16), configurable 24–60 FPS, 8–60 seconds, speed 1.0–1.35x, and a frame-quantized final freeze. Unsupported types/ranges fail fast.
- **Optional AI detail restoration:** if `video_settings.ai_upscale_enabled` is true, each selected clip's source frames are extracted losslessly, enhanced by the external Real-ESRGAN ncnn-vulkan model, then returned to the normal crop/edit pipeline. This is model-generated enhancement, not proof of recovered original detail. AI mode fails fast if the binary or model files are missing; it does not silently pretend Lanczos is AI upscaling. Install the official pinned Linux build with `bash scripts/install_realesrgan_linux.sh`, then enable the setting in `params.json`. The feature toggle is explicit; the current Phonk profile sets it on, so install the executable before rendering. Set it false to use standard FFmpeg scaling without the external tool.
- **Framing modes:** `edit_settings.layout_mode="fill"` fills the 9:16 canvas by cropping; when optional OpenCV detects a recurring person-shaped appearance track, nearby observations can guide a smoothed crop path, otherwise a centered crop is used. `layout_mode="blur_fit"` preserves the entire source frame in the foreground and fills the unused portrait canvas with a blurred background. This is the current profile and is the safer default when football action near the frame edges must not be cut off. Tracking remains a low-confidence appearance proxy, not face recognition or semantic identity.
- Mirror is an explicit `edit_settings.mirror_enabled` boolean; it no longer alternates on a per-clip rule. A horizontal flip can reverse visible text.
- The validated, frame-based EDL now drives source ranges, clip durations, freeze placement and the supported full-timeline audio segment. The renderer rejects unsupported crop rectangles or unsupported audio schedules instead of silently ignoring them.
- The synthetic CI render checks EDL continuity, exact decoded frame count, output dimensions/FPS/duration, audio and full-file decoding.
- Deterministic Python agents run real settings, media, beat, reference, framing, opening-scene-change, planning, niche-evidence, Inspector and Render Critic stages. Hook Analyst supplies an opening cut-cadence proxy, and Niche Analyst supplies a low-confidence craft proxy composite only when required inputs exist; neither claims semantic hook understanding or predicts virality. A structured evidence-linked review conference is stored in the report and printed in the terminal; it is rule-based cross-review, not independent LLM-to-LLM conversation.
- **Ending behavior:** the renderer enforces a final freeze of exactly 2.0 seconds. The current `params.json` enables the skull overlay (`ending_skull_enabled=true`) on the monochrome final freeze, with a 2.0-second hold and enabled impact SFX. A separate short internal drop-impact hold may be inserted when the bass-onset heuristic finds a suitable candidate.
- Missing evidence remains visible. Scene-change counts are not semantic scene understanding; beat timing is a bass-onset/autocorrelation heuristic; the hook agent does not assign semantic hook strength; niche craft scoring remains unavailable until all required metrics are measured.
- Latest verified CI runs pass the current unit-test suite and the synthetic end-to-end render smoke test. Keep test counts in CI output rather than hard-coding them here, so this status note does not become stale. The integration render verifies structural correctness for the normal 20-second 1080x1920, 60-FPS output (1,200 decoded frames), audio, continuous EDL and exact 2-second freeze using generated fixtures. It disables the optional external Real-ESRGAN binary/model path in CI; unit tests cover its fail-fast contract. This does not prove visual quality on real user footage.
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
