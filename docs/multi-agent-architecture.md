# Heyaa Multi-Agent Architecture (Phonk/Montagem)

## Implemented now

The current repository uses deterministic Python agents—not an independent LLM swarm. The orchestration actually runs these stages and writes their result/event records to `output/agent_report.json`:

1. **Settings Agent** validates the real `params.json` values and rejects unsupported or out-of-range settings. It does not compare against hard-coded preferences for speed or Smart Crop.
2. **Media Analyst** reports measured source duration, dimensions, scene-cut count and music duration. Scene cuts are visual-change heuristics, not semantic scene understanding.
3. **Beat Sync Agent** reports whether beat sync is enabled, how many onset candidates were found and whether timing fell back to even pacing. It never treats candidates as guaranteed downbeats.
4. **Planner / EDL Agent** runs the strict EDL validator and checks FPS, resolution, total frames and clip speed against the actual settings.
5. **Niche Analyst** only scores if all normalized craft signals are supplied. Current render code measures a limited beat-alignment proxy from cuts and detected onsets; semantic hook strength, visual clarity, drop impact and motion energy remain unavailable unless measured by a future tested analyzer. Missing inputs produce `insufficient_evidence`, not a fabricated score.
6. **Inspector / Critic** rejects render output when dimensions, FPS, exact decoded frame count, duration, audio presence, full decode or file existence checks fail.
7. **Export Storage** records successful promotion only after blocking technical QA passes. The last known-good final file is preserved if QA blocks the new render.

Every stage returns a structured result with status, findings, recommendations and evidence. The event stream comes from agent execution rather than invented agent-to-agent chat. `main` is the Director/orchestrator: it executes media analysis and rendering, then supplies those real outputs to the agents.

## Not implemented yet

- No independent LLM agents, online trend research agent, visual vision-model reviewer, face/subject tracking, AI upscaling, UI/Agent Room event stream, publish agent or autonomous publishing.
- No automatic quality score for hooks or virality. A craft heuristic is not a prediction of views.
- QA currently checks structural render integrity but does not replace human review of subject framing, image aesthetics, skull placement, flash cadence, audio loudness perception or beat-to-picture feel.
- The EDL v1 renderer supports one full-timeline audio segment. It fails fast for unsupported multi-segment audio schedules.

## Workflow and safeguards

```text
params.json
   -> Settings Agent
   -> source/scene analysis + beat candidate analysis
   -> Director builds integer-frame EDL
   -> Planner validates EDL against settings
   -> FFmpeg renders to temporary path
   -> Inspector validates decoded output
   -> if blocked: preserve existing final and save failure report
   -> if accepted: atomically promote output/final_phonk_20s.mp4
   -> Niche Analyst reports measured metrics and missing evidence
   -> human visual review (required)
```

`main` remains untouched until the project owner explicitly approves a merge. Publishing or uploading user media is outside this implementation.
