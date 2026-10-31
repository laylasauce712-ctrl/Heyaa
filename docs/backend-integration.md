# Backend integration foundation

## Purpose

Heyaa keeps its existing renderer, EDL v1 contract, and analysis heuristics as
the stable core. Optional libraries and models are integrated behind explicit
backend interfaces instead of being imported into the render path directly.

This first layer is intentionally dormant: it adds contracts, registration,
and fallback policy, but does not change the current analysis or render
behavior. No third-party package is installed or required by the base runtime.

## Supported backend roles

| Role | Contract | Current implementation retained |
|---|---|---|
| scene_detector | SceneDetector.detect() → SceneCut observations | FFmpeg scene-change heuristic |
| beat_analyzer | BeatAnalyzer.analyze() → BeatEvent observations | FFmpeg bass-onset / periodic-grid heuristic |
| subject_tracker | SubjectTracker.track() → normalized subject observations | Optional OpenCV HOG appearance tracker |
| semantic_reviewer | SemanticReviewer.review() → timestamped semantic findings | No semantic model currently wired |

All outputs use BackendResult, which records the backend ID, an explicit
status, confidence (when meaningful), warnings, and backend metadata. Individual
observations carry timestamps and normalized coordinates where applicable.
A backend reports evidence; it never writes the EDL, makes export decisions,
or renders video.

## Selection and fallback rules

- Registration is explicit. There is no automatic module discovery, package
  scanning, or arbitrary third-party import at startup.
- A caller selects a backend by its registered ID. The registry does not
  silently pick an arbitrary default.
- A fallback is used only when the selected backend is explicitly unavailable
  or failed. The fallback must be supplied by the caller.
- insufficient_evidence is preserved as a real result; it is not silently
  converted into a success or retried as if the backend crashed.
- Only declared integration exceptions are eligible for fallback. Unexpected
  programming errors propagate and stay visible.
- EDL validation, Inspector, Director hard gates, and atomic export remain
  authoritative. An optional backend cannot bypass them.

## Dependency isolation

Do not add optional model dependencies to the base Python environment or
requirements-vision.txt just to register an adapter. The next integrations
should use separate, pinned requirement files or isolated environments:

- PySceneDetect: separate scene-analysis dependency group.
- Beat This!: separate beat-analysis environment; PyTorch should not become a
  base dependency.
- MediaPipe / Norfair: separate tracking dependency group, evaluated against
  the existing OpenCV HOG path.
- Qwen3-VL: separate semantic-review worker/environment, selected keyframes
  or short windows only; hardware suitability must be checked first.

The adapter process boundary should be preferred for large or conflicting
dependency stacks. A local worker can exchange versioned JSON observations
with the core, while Heyaa validates the response against these contracts.

## Integration checklist for each new backend

1. Record upstream repository, exact version/commit, license, model-weight
   license, supported Python/runtime versions, and transitive dependencies.
2. Install it only in an isolated environment; never upgrade the core runtime
   implicitly.
3. Implement one adapter that maps upstream outputs to these contracts.
4. Keep the existing backend available as the explicit fallback.
5. Compare output evidence on ordinary user workflow inputs without exposing a
   special test mode or changing the selected production backend.
6. Promote the new backend only after a documented quality, latency, memory,
   and failure-behavior comparison.
7. Keep rollback to the previous backend as a configuration change, not a
   code rewrite.

## Non-goals of this foundation

This change does not yet install PySceneDetect, Beat This!, MediaPipe, Norfair,
Qwen3-VL, or Textual. It does not switch any production backend, modify
agent_director.py, or change params.json. The Agent Room remains a later UI
task; current scripts/watch_agents.py stays a terminal trace viewer.
