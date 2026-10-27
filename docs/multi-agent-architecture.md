# Heyaa Multi-Agent Architecture (Phonk/Montagem)

## Current state

The current implementation is a deterministic, rule-based baseline:
- `planner`: checks the approved render settings.
- `niche_analyst`: scores measured craft signals only; it does not predict virality.
- `inspector`: validates basic output properties.
- `run_agent_team`: emits structured events and a JSON report.

These agents are not yet independent LLMs and the event stream is not fully wired into a UI/Agent Room.

## Target pipeline

```text
User request + media
        |
  1. Intake / Settings Agent
        |
  2. Media Analyst ----> audio features, scene cuts, duration, metadata
        |                         |
  3. Trend / Reference Analyst    |
        |                         |
  4. Edit Planner <---------------+
        |
  5. Beat & Timeline Agent
        |
  6. Framing / Crop Agent
        |
  7. FFmpeg Render Agent
        |
  8. QA / Critic Agent ---- failed checks --> Planner (bounded retry)
        |
  9. Export / Storage Agent
        |
  10. Publish Assistant (optional; always asks before posting)
        |
  Human review / approval
```

## Agent responsibilities and contracts

1. **IntakeSettingsAgent** — validates `params.json`, normalizes settings once, and produces a versioned immutable edit config. No hidden defaults that silently contradict the UI.
2. **MediaAnalysisAgent** — probes streams, duration, frame rate, resolution, scene changes, audio loudness and candidate transients. Reports evidence and confidence; does not invent metrics.
3. **TrendReferenceAgent** — analyses user-provided or publicly available reference metadata and pacing patterns. Stores source URL/date and observed facts. Does not copy protected frames or promise virality.
4. **EditPlannerAgent** — emits a versioned EDL with integer-frame boundaries, shot choices, transitions and reasons. Must respect target duration, 9:16 output and speed settings.
5. **BeatSyncAgent** — proposes beat candidates, estimated tempo and confidence. Low confidence falls back to even pacing and reports the fallback.
6. **FramingAgent** — chooses a crop rectangle for each shot. Initial implementation can use deterministic center crop; later add subject/face detection behind an optional dependency. Never label center crop as face tracking.
7. **RenderAgent** — translates validated EDL into bounded FFmpeg filter graphs, writes to a temporary path, and never overwrites the last known-good export until QA passes.
8. **CriticQAAgent** — checks resolution, aspect ratio, duration, audio presence, black/frozen frames, clipping/loudness, crop safety and render errors. Returns structured failures with timestamps and evidence.
9. **ExportStorageAgent** — atomically promotes approved renders, creates a manifest with settings/EDL/tool versions, and manages retention/cleanup. Keep local Termux storage as the first backend; cloud storage is optional.
10. **PublishAssistantAgent** — prepares captions/metadata and platform-specific exports. Posting must be opt-in and require explicit human confirmation; do not store platform credentials in `params.json`.

## Shared event contract

Every agent should return a structured result with:
- `agent`, `stage`, `status` (`ok`, `needs_fix`, `blocked`, `insufficient_evidence`)
- `summary`, `findings[]`, `recommendations[]`
- `evidence{}`, `confidence`, `duration_ms`
- `input_hashes{}`, `config_version`, `edl_version`

Events must come from actual execution. Do not fabricate agent-to-agent chat. Save the event stream to the report so a future UI can render it.

## Implementation order

1. **Stabilize renderer tests** — run the synthetic FFmpeg render test on every branch change and add assertions for 1080x1920, audio, duration, freeze timing and output decodability.
2. **Make settings the single source of truth** — parse and validate config once, then pass it to Planner, EDL and Renderer. Avoid hard-coded values that drift from `params.json`.
3. **Connect EDL to rendering** — translate frame-based EDL segments into FFmpeg inputs/filters and validate all boundaries before starting FFmpeg.
4. **Harden beat sync** — test multiple synthetic tempos, silence, constant audio, noisy transients and half/double-tempo ambiguity. Include confidence and deterministic fallback.
5. **Add QA/Critic feedback** — bounded retries only (for example, one retry), with a report explaining each rejected render.
6. **Improve crop** — preserve full-frame 9:16 center crop first; add optional subject tracking only after tests and dependency checks.
7. **Storage/export and UI events** — manifests and safe temporary files first, then expose real structured events in Agent Room.
8. **Publishing last** — metadata draft/export first; actual posting only with explicit user approval.

## Non-goals and safety rails

- A craft score is not a view-count or virality prediction.
- Do not claim AI upscaling, face tracking or a fully autonomous multi-agent swarm unless implemented and tested.
- Keep `main` untouched until the project owner explicitly approves merging.
- Never publish or upload user media automatically.
