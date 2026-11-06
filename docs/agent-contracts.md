# Heyaa Agent Contracts

Version: 1.0  
Status: current deterministic Python implementation

This document is the canonical role/behavior contract for the existing Heyaa agent stages. These stages are implemented as deterministic Python functions and structured evidence reports; they are not separate LLM agents and their reports are not hidden chain-of-thought. A future LLM assistant may help propose changes, but it must not override these contracts or invent evidence.

## Shared result contract

Every implemented stage returns an `AgentResult` with:
- `agent`: stable stage identifier.
- `status`: one of the stage's documented outcomes.
- `score` and `confidence`: only where the implementation measures a meaningful proxy; otherwise null or conservative.
- `findings`: concise statements supported by actual input/evidence.
- `recommendations`: actionable next steps.
- `evidence`: machine-readable measurements and explicit limitations.

No stage may report a measurement it did not receive or compute. A status of `needs_review` is not a pass on visual quality. `ready_for_human_review` is not human approval.

## Current stage contracts

### 1. Settings Agent — `settings_agent(config)`
**Responsibility:** Validate the actual central settings document before expensive work begins.

**Must validate:** required sections, supported types, finite numeric values, ranges, resolution/FPS/codec/preset, motion-clip bounds (up to 40), freeze durations, booleans, layout/framing modes and EDL mode.

**Must not:** silently repair invalid settings, invent missing user preferences, or mutate tracked configuration just to make a run pass.

**Evidence:** validated profile values, bounds and validation findings.

### 2. Media Analyst — `media_analyst(media)`
**Responsibility:** Report measurable source/media properties.

**Evidence:** duration, dimensions, FPS where available, detected visual-change count and soundtrack duration/stream facts.

**Must not:** call visual scene changes semantic action, character identity, story or quality understanding.

### 3. Beat Sync Agent — `beat_sync_agent(analysis)`
**Responsibility:** Analyze measured low-frequency/onset evidence, estimate rhythmic period and phase, and report a beat-grid confidence proxy.

**Evidence:** source method, candidate count, period, phase and concentration/confidence measures where computed.

**Must not:** claim guaranteed downbeat/drop detection or force every cut onto every beat. Fallback timing must be visible.

### 4. Reference Analyst — `reference_analyst(data)`
**Responsibility:** Validate and report visual cut-pacing evidence from the user's optional reference.

**Lifecycle fields:** `selected`, `available`, `analyzed`, `applied`, `used_for_planning`, `boundary_method`.

**Invariant:** no selected reference means the configured default pacing is permitted. A selected reference must exist, be valid, yield a usable shot-pacing profile and actually contribute to EDL boundaries. If any of these conditions fails, the run blocks before rendering; default pacing must not quietly replace it.

**Must not:** claim semantic understanding of the reference, identify its people, infer its story, copy its frames or replace the separately selected soundtrack.

### 5. Source Chapter Agent — `source_chapter_agent(data)`
**Responsibility:** Report selection of a contiguous source context using measured audio/motion and, when available, appearance-presence evidence.

**Evidence:** candidate chapter ranges, selected start/end, ranking method, coverage and any appearance proxy.

**Must not:** describe activity ranking as semantic action recognition or story understanding.

### 6. Character Lock Agent — `character_lock_agent(data)`
**Responsibility:** Report face-location or HOG/appearance observations, association quality and whether presence evidence could constrain source selection. Face detections may guide framing; they are not biometric identity or re-identification.

**Must distinguish:** hard subject-presence constraint, soft appearance preference, chapter-only context and unavailable tracking.

**Must not:** claim verified identity, face recognition, player re-identification or guarantee that the same real person appears in every selected shot.

### 7. Source Selection / Planner input — measured source intervals
**Responsibility:** Score source scene segments and allocate source ranges in the chosen context without overlap, while respecting source gap and each clip's required source duration.

**Evidence:** candidate counts, selected interval ranges, per-range score/method and explicit fallback reason.

**Must not:** silently switch to source progression when a distinct-edit batch has exhausted the remaining source intervals.

### 8. Framing Agent — `framing_agent(config, edl, ...)`
**Responsibility:** Verify that the EDL framing instructions are supported by the renderer and that the configured layout is respected.

**Rules:** `blur_fit` preserves the whole source frame over a blurred background. `fill` may use a smoothed subject-position crop when usable observations exist; otherwise its actual fallback must be reported.

**Must not:** claim subject-aware cropping if the renderer ignores the crop data, or claim identity understanding from tracking positions.

### 9. Hook Analyst — `hook_analyst(data)`
**Responsibility:** Report opening activity/scene-change evidence as a limited hook-pacing proxy.

**Must not:** claim semantic hook strength or predict audience retention from scene changes alone.

### 10. Planner / EDL Agent — `planner(context)`
**Responsibility:** Validate the frame-based EDL contract against the actual output profile and renderer-supported operations.

**Must validate:** schema version, ordered contiguous frame ranges, source and output durations, frame rate, dimensions, speed, clip-count bounds, freeze positions/durations and supported crop/effect operations.

**Must not:** treat a syntactically valid EDL as proof that the edit looks professional.

### 11. Niche Analyst — `niche_analyst(metrics, tags)`
**Responsibility:** Score only normalized craft metrics that were actually measured for the requested style.

**Must expose:** missing metrics, proxy-score type and confidence restrictions.

**Must not:** claim virality, future views, rewards eligibility or semantic trend alignment without real supporting measurements.

### 12. Inspector — `inspector(report)`
**Responsibility:** Verify the final encoded artifact's measurable technical properties.

**Evidence:** file existence/size, stream presence, width/height, codec, configured FPS, duration, decoded frame count and full-decode result.

**Must not:** label a technical pass as visual approval.

### 13. Render Critic — `render_critic(metrics)`
**Responsibility:** Evaluate measured technical risks such as black intervals, silence/low loudness, peak level and sampled visual risks (blur, very dark frames and unintended still intervals), including measurement completeness.

**Outcomes:** reject or block on required missing/failed evidence; use `needs_review` for measured warnings.

**Must not:** claim composition, subject visibility, emotional impact or style fidelity unless an explicit visual measure is added and validated.

### 14. Director — `director_agent(results, reference_required=False)`
**Responsibility:** Combine the real stage results into an explicit technical decision.

**Required gates:** settings, planner, inspector, render critic and (when selected) the reference lifecycle gate. Blockers must include the responsible stage, status and findings.

**Decision vocabulary:** `allow_technical_export` or `block_export`; the top-level orchestration may expose `ready_for_human_review` after a technical pass.

**Must not:** override a blocked stage, convert missing evidence to success, or claim the user approved/published the result.

### 15. Export Storage — `export_storage_agent(...)`
**Responsibility:** Safely move a technically accepted render into its run output location without corrupting a prior known-good file.

**Current limitation:** the current exporter is a technical storage/promotion step, not an enforced user-facing approval control. Do not equate it with approval for TikTok or transfer to the approved `releases/` area. A separate human approval action is still required before that future release workflow can be considered complete.

## Cross-agent invariants

1. Preserve one Heyaa renderer and the existing frame-based EDL; new observers or reference projects must not introduce a second production engine.
2. Each report must cite its own structured evidence and state limitations. Do not invent LLM dialogue or hidden reasoning.
3. The user chooses source video, music and optional reference. No source-provenance, license-category or rights-manifest gate belongs in the render pipeline.
4. Reference is optional; when selected, it must be demonstrably applied to EDL timing or the run blocks.
5. The user chooses the number of distinct edits with `--edits 1..5`. A motion-clip count is a separate per-edit setting.
6. Distinct-edit mode reserves source intervals after each successful EDL and excludes them before planning the next edit. If footage is insufficient, report fewer edits instead of repeating source ranges.
7. Default rendering is one output. Legacy `--variants` is a comparison/debug mode and does not satisfy the distinct-edit requirement.
8. Final technical QA and human approval are separate gates.
9. Preserve the profile invariants unless the user explicitly changes them: vertical 1080x1920, configured frame rate, exact 2.0-second final freeze, selected Phonk/Montagem controls and validated AI-upscale execution.
10. Any future LLM prompt must be versioned, constrained by this document, and evaluated against the deterministic contract before it can influence production decisions.
