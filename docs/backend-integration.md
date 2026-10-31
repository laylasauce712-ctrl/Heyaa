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

The first model backend is PySceneDetect, which is already described above.

## Second optional adapter: Beat This!

Beat This! 1.1.0 (MIT code and published weights) is pinned to the small0
checkpoint and runs CPU-only in tools/beat-analysis/.venv. The installer uses
the official PyTorch CPU wheel index; torch and torchaudio do not enter Heyaa's
base interpreter. The first inference may download the upstream small0 weights
(about 8.1 MB per the upstream README).

The worker analyzes at most 45 seconds from the start of the selected music
track and reports separate beat and downbeat timestamps. The current
bass-onset/periodic-grid heuristic remains authoritative for all production
timing. Agreement is recorded within 100ms; it is a detector comparison, not
ground-truth accuracy. The backend is not a semantic drop classifier.

Remove only tools/beat-analysis/.venv to disable this observer. It does not
touch the PySceneDetect or Real-ESRGAN environments.

## Third optional adapter: Norfair association

Norfair 2.3.0 (BSD-3-Clause) is pinned in `requirements-tracking.txt` and
installed only in `tools/norfair-analysis/.venv`. It is used as an
association-only backend over the normalized person-shaped boxes and
appearance histograms already produced by Heyaa's OpenCV HOG detector. It does
not run a detector or introduce model weights.

The association distance uses Kalman-predicted center movement, normalized
HOG color histograms, and box height. It is bounded to a 2.2-second gap and
records track IDs, spans, and agreement with the current greedy HOG association.
Norfair runs only after the same HOG detector has produced its sampled boxes.
The current greedy tracker remains authoritative; Norfair cannot change the
selected source, subject, crop, or EDL. Track IDs are temporary tracking IDs,
not verified identity. The coarse scan of multiple chapter candidates skips
Norfair so it does not multiply tracking work before a chapter is selected.

The worker is separate from Heyaa's core interpreter. When OpenCV is absent,
there are no HOG observations and Norfair is not invoked. Removing only
`tools/norfair-analysis/.venv` disables the observer. MediaPipe Pose is not
included in this phase: its current Tasks privacy notice says that aggregate
performance/usage metrics are sent to Google, with no direct opt-out described
in the current documentation. The source video itself remains local, but this
telemetry is not aligned with the strictest local-only preference.

## Dependency isolation

Do not add optional model dependencies to the base Python environment or
requirements-vision.txt just to register an adapter. The next integrations
should use separate, pinned requirement files or isolated environments:

- PySceneDetect: isolated `requirements-scenes.txt` environment and shadow adapter.
- Beat This!: isolated CPU-only `requirements-beats.txt` environment and shadow worker.
- MediaPipe Pose: not enabled due to Tasks usage/performance telemetry; Norfair is an isolated HOG-association observer.
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

This change does not install MediaPipe, Qwen3-VL, or Textual. It does not
switch any production analysis decision: FFmpeg remains authoritative for
scene-cut timestamps, the current bass-onset/periodic-grid heuristic remains
authoritative for beat timing, and the existing HOG/greedy tracker remains
authoritative for subject observations. PySceneDetect, Beat This!, and Norfair
only record shadow evidence. The Agent Room remains a later UI task; current
scripts/watch_agents.py stays a terminal trace viewer.
