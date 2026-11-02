# Heyaa Product Contract

This document records product decisions that new features and integrations must preserve.

## Product shape

- Heyaa remains one local-first product with one rendering engine, one central settings source and one local output root.
- Do not import or embed a second complete video editor/rendering engine. External repositories are technical references for narrow capabilities and design patterns only.
- Keep the existing frame-based EDL and the current agent orchestration architecture. Improvements must extend the existing stages rather than replace them.
- The current Python/FFmpeg renderer remains the production path. Optional observers/backends must not silently change production output until their quality has been measured and approved.

## Existing architecture to preserve

Settings validation; source/media analysis; music beat and bass-onset analysis; reference analysis; source chapter selection; subject appearance tracking; source-range planning; framing/crop planning; hook and niche evidence; frame-based EDL validation; FFmpeg rendering; Render Critic; Inspector; Director; Export Storage; structured progress events and analysis cache.

These are evidence-based Python modules today. Do not describe them as separate LLMs or invent agent dialogue. The Agent Room/UI is a future presentation layer over real events and reports.

## Media inputs

- The user chooses the source video, soundtrack and optional visual reference.
- Accept supported local files and supported URLs through the existing input-validation/download layer.
- Do not add self-filmed/licensed/third-party provenance categories, rights manifests or copyright-eligibility gates to the render pipeline. Source choice and rights decisions remain with the user.
- Technical file validation (valid stream, duration, accessible path and supported format) remains required.

## Reference contract

- Reference is optional.
- When no reference is selected, Heyaa may use its configured default pacing.
- When a reference is selected, the pipeline must verify that it exists, is a valid video and produces a usable measured pacing profile.
- A selected but missing, invalid or unusable reference must fail clearly before rendering. Never silently substitute default pacing and then report the run as reference-driven.
- Reports must distinguish reference selected, reference available, reference analyzed and reference timing actually applied.
- The current analysis is shot-cut timing/pacing only. Do not claim semantic understanding of people, story or effects unless a future implementation measures those capabilities.

## User-selected edit count

- The user chooses how many separate edits to generate for one source/batch.
- Do not hard-code five outputs or generate extra variants by default.
- Each requested edit must be a distinct edit plan, not merely a relabelled source-time curve or the same render copied to another filename.
- Keep the phonk/montagem look and selected source/music/reference consistent while varying the actual edit decisions enough to make each output meaningfully distinct.
- If the media cannot support the requested number of meaningfully different outputs, report the limitation honestly rather than manufacturing duplicates.
- A user-selected edit count is different from the number of motion clips inside one EDL. Keep those controls separate.

## Output and review

- All local artifacts live under one project-level output root.
- Target directory contract: `output/runs/` for working runs and reports, `output/releases/` for user-approved final exports, and `output/archive/` for retained older releases.
- Keep technical QA distinct from human approval. A technically valid render is ready for the user to review; it is not automatically approved for publishing.
- Never promote an edit to the approved releases area without an explicit user approval action.
- Preserve the latest-known-good output when a new render fails.

## Visual product direction

- Build one local UI inside the Heyaa repository; do not create a parallel app or a second backend.
- The intended look is a dark, cinematic creative-studio/agency interface with one consistent theme and icon system.
- Initial theme tokens: near-black canvas (#0B0D12), charcoal surfaces (#131722 / #1A2030), restrained violet primary accent (#8B5CF6), cool cyan for technical telemetry (#38BDF8), neutral text hierarchy and clear warning/error states. Avoid neon overload, gradient-heavy cards and dashboard clutter.
- The interface should expose source/music/reference selection, user-selected edit count, render settings, real Agent Room events, previews, QA results, explicit approval and local release/archive browsing.
- Use Lucide from https://github.com/lucide-icons/lucide as the single icon family. It is an actively maintained SVG icon toolkit with an ISC license; use its consistent stroke style and do not mix unrelated icon packs.
- No PowerShell. Development and launch instructions must use WSL Ubuntu and Bash. The PC performs rendering; the phone receives finished exports.

## Quality and proof

- Synthetic CI proves structural behavior, not visual editing quality.
- Before claiming a quality feature is production-ready, test it on real source footage, soundtrack and (when selected) a real reference.
- Verify the final video by both visual inspection and listening. Verify Real-ESRGAN from actual execution evidence, not only a config flag or installed binary.
- Preserve the 1080x1920 vertical profile, configured frame rate, exact 2.0-second final freeze and current approved visual/audio controls unless the user explicitly changes them.
- No code, branch, merge, settings or release changes should bypass review of the exact scope and evidence.
