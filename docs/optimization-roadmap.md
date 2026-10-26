# Heyaa optimization roadmap

## Current verified code facts
- Target output configured as 1080x1920 (9:16), 60 FPS, 20 seconds.
- Speed defaults to 1.1x.
- Current foreground is still a 1080x1080 square over a blurred 1080x1920 background; this is not true full-frame 9:16 smart crop.
- Mirror was previously hard-coded as a horizontal flip on alternating clips; it is being changed to an explicit boolean setting.
- Beat detection is a low-frequency transient heuristic, not a validated beat/downbeat model.
- EDL v1 exists but is not connected to the renderer.
- No evidence yet that independent Critic/Inspector agents run and affect rendered output.

## Next stages
1. Mirror: explicit horizontal flip setting, separate from flash/shake/zoom/freeze.
2. Smart crop: separate 9:16 output canvas from crop window; do not call center crop AI smart crop.
3. CI tests: run timeline, EDL validation, settings and filter tests on each PR.
4. Render QA: verify dimensions, duration, audio, black frames, audio/video duration delta and representative frames.
5. Beat sync: improve onset detection, expose confidence/fallback and test synthetic beat fixtures.
6. Agents: typed Planner -> Director -> Renderer -> Inspector -> Critic stages with structured outputs and real event logs. Critic can reject and trigger bounded retry; Director remains final authority. Chat Room shows real events, not simulated conversation.
7. Mobile performance: benchmark render time and memory on Termux before claiming optimization.

## Acceptance gates
- Unit tests pass in CI.
- One settings object feeds all pipeline stages without drift.
- A deterministic synthetic render is checked automatically.
- Agent events represent actual decisions/results.
- Do not merge to main until the user reviews evidence.
