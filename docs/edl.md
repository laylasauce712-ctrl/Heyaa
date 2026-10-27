# Heyaa EDL v1 — M1a contract

The Edit Decision List (EDL) is a versioned JSON plan for a future frame-accurate renderer. The renderer now builds and validates a frame-contiguous EDL from params.json and uses its clip entries to drive segment rendering. The freeze entry is represented explicitly in the EDL; the existing FFmpeg impact filter implements its visual treatment.

## Top-level fields

- version: required integer, currently 1.
- fps_num and fps_den: positive integers describing rational frame rate, e.g. 30000/1001.
- width and height: positive output dimensions.
- total_frames: exact positive output frame count.
- video: non-empty ordered list of clip/freeze items. Starts at frame 0, stays contiguous, and ends exactly at total_frames.
- audio: optional source audio segments, each contained within the project duration.

Unknown fields and unsupported versions are rejected so schema changes stay explicit.

## Video item types

Every item has type, start_f, and positive dur_f. Positions and durations are integer frames, not floating-point seconds.

Clip items additionally require source, source_start_f, source_dur_f, speed, and crop. Speed is limited to 0.25–4.0; output duration must match source duration divided by speed within one frame. Crop x/y/w/h are normalized source-frame fractions and must form a positive rectangle inside [0,1].

Example clip JSON:

    {"type":"clip","source":"input.mp4","source_start_f":0,"source_dur_f":90,"start_f":0,"dur_f":90,"speed":1.0,"crop":{"x":0,"y":0,"w":1,"h":1}}

Freeze items require source_frame_f and may specify a non-empty renderer-defined effect string. Duration is the number of output frames to hold the still.

    {"type":"freeze","source":"input.mp4","source_frame_f":89,"start_f":90,"dur_f":15,"effect":"phonk-freeze"}

Audio items use source, source_start_f, start_f, dur_f, and optional gain_db, fade_in_f, fade_out_f. Frame values are non-negative integers, duration is positive, and audio must fit within total_frames. Fade lengths cannot exceed segment duration.

## API and compatibility

- validate_edl(edl) returns the same object or raises EDLValidationError.
- frames_to_seconds and seconds_to_frames support rational FPS.
- edl_mode(params) recognizes off, shadow, and on; absent/invalid values resolve to off. The integrated renderer requires edl_mode=on; off/shadow are not supported by the current render path.
- No third-party dependencies are added.

## Checks

Run unit tests with: python -m unittest discover -s tests/unit -v
Optional fixture generation: sh tests/integration/make_fixtures.sh (requires FFmpeg). Fixture generation is not a visual-quality test.

## M1a non-goals

No changes to existing filters, beat detection, crop behavior, freeze effects, or agent orchestration. No claims of AI upscaling or automated visual-quality verification. Renderer integration and A/B visual review are later milestones.
