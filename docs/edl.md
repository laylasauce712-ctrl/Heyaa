# Heyaa EDL v1 — integrated frame-based edit contract

The renderer builds, validates and consumes an EDL from `params.json`. The validator requires explicit FPS denominator and clip speed. The validated EDL drives ordered clip boundaries, project frame count, clip speed, source seek ranges, audio source and freeze placement. Every project frame must be covered exactly once, with no gaps, overlaps or zero-length items.

## Fields and units

Top-level fields: `version`, `fps_num`, `fps_den`, `width`, `height`, `total_frames`, `video[]`, and `audio[]`.

Video items use integer `start_f` and `dur_f` project frames. Clip entries also carry `source_start_f`, `source_dur_f`, `speed` and normalized `crop`. In EDL v1, source range ticks are measured at the project FPS and converted to seconds for FFmpeg seeking; they are not guaranteed to equal native source-frame indices when the source frame rate differs. Crop currently describes the full normalized source area; FFmpeg applies a centered 9:16 aspect crop. This is not face or subject tracking.

Freeze entries identify the last edited timeline frame and the number of project frames to hold. The renderer uses frame-count-based clone padding and trims the output to exactly `total_frames`.

Audio entries carry source, source start, project start, duration, gain and optional fades in project-frame units. The current profile supports one audio segment spanning the full output timeline, and rejects unsupported multi-segment or non-zero-timeline audio rather than pretending to implement it. `music_loop` controls looping; when disabled, short music is padded with silence. Beat candidates are extended across repeated music cycles only when looping is enabled and the source provides enough detected candidates.

## Settings, render QA and agents

`params.json` is the single settings input. Unsupported or out-of-range values fail fast rather than being silently clamped. The Director validates EDL frame continuity, output size/FPS, target frame count, clip speed/count, freeze placement and renderer crop support before promotion.

The Inspector verifies 1080x1920, configured FPS, codec mapping, exact decoded frame count, target duration, audio presence, file existence and full-file decode. The Render Critic runs FFmpeg `blackdetect` and `volumedetect` measurements. It rejects silent/near-silent audio and flags long black intervals, very low average level or peaks near 0 dBFS. These are simple technical risk proxies, not aesthetic review.

The deterministic Settings, Media, Beat Sync, Reference, Framing, Hook proxy, Planner, Niche, Inspector, Render Critic, Director and Export Storage stages write structured evidence/events to `output/agent_report.json`. The Director records an explicit allow/block decision. Export Storage atomically promotes the temporary file only after required gates pass. On a blocked decision, the previous final export is preserved.

These are deterministic Python modules, not independent LLM agents or a UI/Agent Room. Missing niche metrics correctly produce `insufficient_evidence`; no virality score is fabricated.

## Validation

```sh
python -m unittest discover -s tests/unit -v
bash tests/integration/render_smoke.sh
```

CI on code commit `d2ab640` passed 41 unit tests and the synthetic FFmpeg end-to-end smoke test. The test produces generated media, not a user's real footage; it proves structural pipeline checks, not visual quality or viral performance. Human visual review remains required.
