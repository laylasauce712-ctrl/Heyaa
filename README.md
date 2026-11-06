# Heyaa

**Heyaa** is a local-first Phonk / Montagem video-editing workflow. It plans vertical edits from source footage, a separately selected Phonk soundtrack, and an optional visual pacing reference, then renders through the existing FFmpeg pipeline.

The project is kept in one repository and one renderer. The local Studio is a control surface for that renderer, not a second editing engine.

## Start the local Studio

Requirements:

- Python 3.10 or newer
- FFmpeg and `ffprobe` on your WSL/Linux `PATH`
- `yt-dlp[default]` when using TikTok or YouTube post/video links
- Optional OpenCV for the lightweight appearance/framing proxy

From the repository root:

```bash
bash scripts/start_heyaa_ui.sh
```

Open **http://127.0.0.1:8765** in your browser. The server binds to localhost only. Stop it with `Ctrl+C` in the terminal.

The Studio reads local media from `input/`, writes runs and exports under `output/`, and saves UI-specific settings to the ignored `params.local.json`. It does not overwrite tracked `params.json` when you change controls in the UI.

## Media inputs

A render needs:

1. One source video (local file or one supported URL).
2. One Phonk soundtrack (local audio or one supported URL).
3. An optional visual pacing reference.

A reference guides measured cut timing only. Its video frames and audio are not used as the final footage or soundtrack by the standard renderer. When a reference is selected, its cut pacing must be measurable; Heyaa blocks the render rather than silently pretending it applied an unusable reference.

Supported links are single TikTok posts/share links, single YouTube videos, and direct HTTPS media URLs. Platform access can be restricted; Heyaa does not use browser cookies or bypass logins. Only download and reuse media you own or are authorized to use. Details: [Media links](docs/media-links.md).

## Default edit profile

- 20-second Phonk / Montagem edit
- 1080 × 1920 portrait, 60 FPS, H.264
- Final freeze held for exactly 2.0 seconds
- At least 11 motion clips per edit; up to 40
- Fill framing, mirroring off, skull overlay off
- Optional beat sync, flash, bass processing, subject/framing proxy and impact SFX

AI Restore is **off by default** so a fresh clone can render without separately installing the ignored Real-ESRGAN executable and model weights. Enable it in the Studio only after those assets and a usable hardware-backed Vulkan device are available. Installation notes: [optimization roadmap](docs/optimization-roadmap.md) and [multi-agent architecture](docs/multi-agent-architecture.md).

### Local batch using the reference video's soundtrack

When you specifically want the reference video's own audio as the soundtrack, place the source footage at `input/test_video.mp4` and the reference at `input/reference.mp4`, then run:

```bash
bash scripts/export_reference_audio_batch.sh
```

The script extracts the reference audio and prepares a temporary profile with three distinct 20-second edits, 1080 × 1920 at 60 FPS, at least 11 motion clips, mirror enabled and the exact 2-second final freeze. **AI Restore is off by default**, so ordinary exports do not require Real-ESRGAN, Vulkan or a dedicated GPU. Heyaa uses its standard FFmpeg scaling path instead. Set `HEYAA_ENABLE_AI_UPSCALE=1` explicitly to request Real-ESRGAN; that optional mode checks for model weights and a hardware-backed Vulkan device before rendering. Set `HEYAA_EDIT_COUNT=1` through `5` to choose another batch size; the default is three. Optional path overrides are `HEYAA_VIDEO_PATH`, `HEYAA_REFERENCE_PATH`, `HEYAA_REFERENCE_AUDIO_PATH` and `HEYAA_EXPORT_BASE_PROFILE`.

This is a local WSL/Linux render workflow, not a GitHub-hosted renderer. GitHub Actions checks code and script syntax; the real media and exports remain on the render worker. For a phone-accessible service, deploy the existing cloud API, private media storage and worker as a hosted service; GitHub stores the source and checks changes but is not the long-running render server. The cloud worker can produce standard FFmpeg exports on CPU, with AI Restore reserved for a separately provisioned GPU worker when explicitly requested.

## What the Agent Room shows

The pipeline consists of deterministic Python agents and renderer stages. They report measured media properties, candidate timing, source selection, EDL validation, render inspection and export decisions. The Studio displays recorded events, named speakers/recipients when present, findings, recommendations and compact evidence.

These are evidence-linked reports, **not** independent LLM agents or simulated private conversations. While the render process is active between events, the Studio shows an explicit active-process indicator. The percentage bar is intentionally indeterminate because the renderer does not currently emit a reliable overall percentage.

Full records are written to each run directory:

- `progress.jsonl` — timestamped pipeline and agent events
- `agent_report.json` — structured findings, decisions and missing evidence
- `edit_decision_list.json` — frame-based edit decision list
- `contact_sheet.png` — render contact sheet when available

More detail: [Agent contracts](docs/agent-contracts.md), [multi-agent architecture](docs/multi-agent-architecture.md), and [usage](docs/usage.md).

## Render, inspect and approve

The Studio can create a quick preview or a full render. Outputs are stored under `output/runs/<run-id>/`. A technically accepted render is still **for human visual review**; approving it in the Studio creates a separate copy under `output/releases/`. TikTok publishing remains manual.

Run the unit tests with:

```bash
python3 -m unittest discover -s tests/unit -q
```

Run the integration smoke render with:

```bash
bash tests/integration/render_smoke.sh
```

The smoke render uses synthetic fixtures. Passing it does not establish real-footage visual quality, successful access to a particular TikTok URL, or GPU upscaling performance on your machine.

## Repository workflow

The consolidated renderer and Studio integration was merged into `main` in [PR #11](https://github.com/laylasauce712-ctrl/Heyaa/pull/11). Reusable code and automated checks belong in GitHub; input media, generated exports, local settings, model weights and credentials stay on the local machine and must not be committed.
