# Backend integration foundation

## Purpose

Heyaa keeps its existing renderer, EDL v1 contract, and analysis heuristics as
the stable core. Optional libraries and models are integrated behind explicit
backend interfaces instead of being imported into the render path directly.

The shared contracts and registry are dependency-free. The first optional
engine, PySceneDetect, is integrated as a separately installed shadow observer;
it does not change current planning or render decisions. No third-party package
is required by the base runtime.

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

## First optional adapter: PySceneDetect

The PySceneDetect adapter is pinned to upstream version 0.7.2 (BSD-3-Clause).
It uses the official ContentDetector API and maps cut timestamps into the
shared SceneCut evidence contract. Its dependency is installed only into
tools/scene-analysis/.venv via scripts/install_scene_backend_linux.sh and
requirements-scenes.txt; the Heyaa core Python environment is not modified.

When that isolated environment exists, the ordinary render workflow invokes
the scene worker on up to three 20-second windows distributed across the
analyzed source. FFmpeg remains the primary detector and its timestamps remain
the only ones used for existing planning. PySceneDetect results are recorded
as a shadow observation, with one-to-one agreement counts within 150ms. These
counts compare two detectors; they are not accuracy, precision, or recall
because neither detector is ground truth. Worker absence, timeouts, decode
errors, and other shadow failures do not stop rendering or change EDL decisions.

Remove only tools/scene-analysis/.venv to disable this optional observer; the
installer refuses to replace an unexpected existing path. Existing local
tools/realesrgan files and the base runtime are left untouched.

## Dependency isolation

Do not add optional model dependencies to the base Python environment or
requirements-vision.txt just to register an adapter. The next integrations
should use separate, pinned requirement files or isolated environments:

- PySceneDetect: isolated `requirements-scenes.txt` environment and shadow adapter.
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

This change does not install Beat This!, MediaPipe, Norfair, Qwen3-VL, or
Textual. It does not switch the production scene detector: FFmpeg remains the
only source of scene-cut timestamps used by the current planner. The optional
PySceneDetect worker only records shadow observations. The Agent Room remains
a later UI task; current scripts/watch_agents.py stays a terminal trace viewer.
