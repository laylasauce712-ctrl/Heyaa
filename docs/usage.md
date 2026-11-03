# Heyaa Local Usage (WSL Ubuntu / Bash)

All commands in this guide use WSL Ubuntu and Bash. PowerShell is not part of the supported workflow.

## One edit (default)

Place the source video and soundtrack at:

- `input/test_video.mp4`
- `input/phonk.mp3`

A reference is optional. When selected, place it at `input/reference.mp4`.

From the repository root:

```bash
python3 src/agent_director.py
```

The ordinary run creates one output under `output/runs/<run-id>/`.

## Ask for several distinct edits

Choose the requested number from 1 through 5:

```bash
python3 src/agent_director.py --edits 5
```

Each successfully rendered edit is stored separately:

```text
output/runs/<run-id>/
├── edits_manifest.json
├── source_usage_ledger.json
└── edits/
    ├── edit_01/
    │   ├── final_phonk_20s.mp4
    │   ├── agent_report.json
    │   └── edit_decision_list.json
    └── edit_02/
        └── ...
```

The batch reserves the motion-clip source intervals used by each successful EDL before planning the next edit. It also protects the configured source gap. If there is not enough unused material for another complete edit, it stops and records a partial batch in `edits_manifest.json`. The default remains one render.

`--variants` is a legacy comparison/debug option and is not the distinct-edit feature. Do not use it as a substitute for `--edits`.

## Use a reference

A reference is optional. A selected reference becomes required and must be usable:

```bash
python3 src/agent_director.py --reference-url "https://example.com/reference.mp4"
```

Or place the reference at `input/reference.mp4` and run the normal command. If the selected reference is missing or the measured pacing cannot be safely applied to the EDL, the run blocks instead of silently using default pacing.

## Use supported URLs

The CLI supports source-video, music and reference URLs:

```bash
python3 src/agent_director.py \
  --video-url "https://example.com/source.mp4" \
  --music-url "https://example.com/phonk.mp3" \
  --reference-url "https://example.com/reference.mp4" \
  --edits 3
```

For a TikTok post/share URL:

```bash
python3 src/agent_director.py --tiktok-url "https://www.tiktok.com/@creator/video/1234567890123456789"
```

The user chooses the source content. Heyaa performs technical media validation; it does not classify footage as self-filmed, licensed or third-party.

## Approve one render for local release

Technical QA makes an output ready for human review; it does not approve it automatically. Review the MP4, then explicitly approve the exact file:

```bash
python3 scripts/approve_release.py \
  output/runs/<run-id>/final_phonk_20s.mp4 \
  --confirm
```

For one item from a distinct-edit batch:

```bash
python3 scripts/approve_release.py \
  output/runs/<run-id>/edits/edit_01/final_phonk_20s.mp4 \
  --confirm
```

The approval command checks the Agent Report, Inspector, Export Storage, final EDL freeze and actual media streams/dimensions/FPS via `ffprobe`. It copies the selected render and evidence into:

```text
output/releases/<run-id>/primary/
output/releases/<run-id>/edit_01/
```

Existing releases are never overwritten, and the source file under `runs/` is retained. Upload to TikTok remains a separate manual action in TikTok Studio.

## Watch the real agent events

In a second WSL terminal:

```bash
python3 scripts/watch_agents.py
```

To inspect the latest completed report once:

```bash
python3 scripts/watch_agents.py --once
```

The watcher displays recorded stage events and evidence; it is not a separate LLM chat.

## Important verification limit

Synthetic CI verifies the EDL contract, reference lifecycle, renderer structure, batch ledger and technical QA gates. It does not certify visual quality on your own source/music/reference, nor prove that Real-ESRGAN ran successfully on your PC. Those still need a real local review.
