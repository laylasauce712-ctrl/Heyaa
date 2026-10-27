# Heyaa EDL v1 — integrated frame-based edit contract

The renderer builds, validates and consumes an EDL from `params.json`. The validator requires explicit FPS denominator and explicit clip speed. The EDL is the source of truth for ordered clip boundaries, project frame count, clip speed, source seek ranges, audio source and freeze placement. A validated EDL must cover every project frame exactly once: no gaps, overlaps or zero-length items.

## Fields

Top-level fields: `version`, `fps_num`, `fps_den`, `width`, `height`, `total_frames`, `video[]`, and `audio[]`.

Video items use integer `start_f` and `dur_f` project frames. Clip entries also carry `source_start_f`, `source_dur_f`, `speed` and normalized `crop`. In this renderer's v1 profile, source range ticks are measured at the project FPS and converted to seconds for FFmpeg seeking; they are not guaranteed to equal the source file's native frame index when its frame rate differs. Crop currently describes the full normalized source area; the renderer applies a centered 9:16 aspect crop. That is not face tracking.

Freeze entries name the frame at the end of the edited timeline and the number of project frames to hold. The renderer uses frame-count-based clone padding and trims the output to exactly `total_frames`.

Audio entries carry source, source start, project start, duration, gain and optional fades in project-frame units. The current render profile intentionally supports one audio segment spanning the entire output, and rejects unsupported multi-segment/non-zero-timeline audio instead of silently pretending to implement it. `music_loop` controls whether the audio input is looped; when disabled, short music is padded with silence.

## Settings and QA

`params.json` is the single configuration input. Unsupported or out-of-range values fail fast rather than being silently clamped. The director validates the EDL before FFmpeg starts. Render QA checks 1080x1920, output FPS, exact decoded frame count, audio presence, duration and a full-file decode. The previous final export is not replaced until blocking technical QA passes.

The `agent_report.json` contains structured events/results from the deterministic settings, media, beat-sync, planning, niche-review, inspector and export stages. These are not independent LLM agents and are not a UI/Agent Room; no model chat is fabricated.

## Validation

```sh
python -m unittest discover -s tests/unit -v
bash tests/integration/render_smoke.sh
```

The integration test uses generated synthetic media. It proves the technical pipeline checks but does not prove visual quality on a user's actual footage or predict virality. Human visual review remains required.
