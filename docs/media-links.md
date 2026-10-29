# Run Heyaa from media links or local files

Heyaa accepts YouTube video pages, TikTok post/share URLs, and direct HTTPS media URLs
for source footage, the Phonk soundtrack, and an optional pacing reference. Local files
remain supported. Use only media you own or have permission to download and reuse; platform
terms and copyright still apply.
Use media you own or have permission to download and reuse. Platform restrictions apply.

## Requirements

- Python 3.10+
- FFmpeg and ffprobe available on PATH
- yt-dlp for YouTube and TikTok post/share URLs
- Optional: OpenCV for a lightweight person-shape / appearance-consistency tracking proxy

Install yt-dlp in WSL:

    python3 -m pip install --user -U "yt-dlp[default]"

Optional person tracking:

    python3 -m pip install --user opencv-python-headless

OpenCV is optional. If it is missing or cannot find a stable person-shaped track,
Heyaa falls back to scene-cut-density context selection and the centered 9:16 crop.
The HOG detector is a visual-consistency proxy, not face recognition or reliable
identity/story understanding; it can miss people, especially in close-up, occlusion,
low light, or unusual camera angles.

## Run from WSL

From the repository root:

    python3 src/agent_director.py \
      --video-url 'https://www.youtube.com/watch?v=SOURCE_VIDEO_ID' \
      --music-url 'https://www.youtube.com/watch?v=PHONK_TRACK_ID' \
      --reference-url 'https://www.youtube.com/watch?v=REFERENCE_VIDEO_ID'

You can download a TikTok post directly as source footage with the dedicated option:

    python3 src/agent_director.py --tiktok-url 'https://www.tiktok.com/@creator/video/1234567890123456789'

The existing `--video-url` option also accepts TikTok post/share URLs. TikTok links can be used
for the soundtrack or optional visual reference through `--music-url` and `--reference-url`.
Use one post URL or an official TikTok short share link (for example, `https://vm.tiktok.com/...`).
Do not pass both `--video-url` and `--tiktok-url`.

TikTok downloads use yt-dlp with bounded timeouts and retries, and do not use browser cookies or
login credentials. Private, login-gated, removed, or region-restricted posts may not be downloadable;
Heyaa does not bypass those restrictions. Use media you own or have permission to download and reuse.

You can also supply direct HTTPS media URLs, for example a host-provided MP4 or
MP3 download URL:

    python3 src/agent_director.py \
      --video-url 'https://cdn.example.org/source.mp4' \
      --music-url 'https://cdn.example.org/track.mp3'

Direct downloads must respond with a media-compatible content type, are limited
to 2 GiB per file, and use network timeouts. A web page that merely displays a
video is not a direct media URL. If the host requires a login, cookies, or
specialized access, use a local file instead.

The reference is optional; omit --reference-url if you do not have one. It is a
**visual pacing reference only**: its audio is never extracted for the final edit.
Always supply your desired Phonk separately with `--music-url`, or keep your own
track at `input/phonk.mp3`. Supplying a reference must never replace that track.

You may mix URLs with local files: if `--video-url` is omitted,
`input/test_video.mp4` must already exist; if `--music-url` is omitted,
`input/phonk.mp3` must already exist.

## Long source footage and 20-second edits

The default project profile targets a 20-second Phonk/Montagem edit. When source
footage is at least 60 seconds long (or three times the moving-edit duration,
whichever is greater), the source selector searches the full recording rather
than only the shorter framing/tracking context window. It measures bounded
candidate windows (up to 4 seconds each, split at detected scene changes when
possible) and ranks them using source loudness and motion proxies; clips are then
assigned in source-time order without reusing overlapping ranges. The report
records the search scope, candidate count, selected segments and cache status.

This selection does not understand football events, identify the same player, or
guarantee that a loud/moving interval is a goal, skill, or meaningful action.
Human review is still required. If feature measurement is unavailable, the
fallback progresses through the selected source scope instead of limiting a
long recording to the tracking context window.

YouTube and TikTok downloads show live yt-dlp progress and use IPv4 to avoid networks
where the IPv6 route to media/CDN hosts is broken. Source footage is capped at
1080p landscape or 1080x1920 portrait (matching the 1080x1920 output); the optional
pacing reference is capped at 720p landscape or 720x1280 portrait. This helps
avoid downloading unnecessarily large 1440p/4K files while retaining enough
resolution for a vertical edit.

Timeouts are bounded by source type: 45 minutes for source video and 15 minutes
for music/reference, with a 20-second socket timeout and limited retries. Network
and extractor errors stream directly into the terminal and log instead of being
hidden. If YouTube blocks the request or the connection stalls, Heyaa exits with
a clear error; switching tools cannot guarantee bypassing platform restrictions.
Use a direct media URL or a local file when permitted and available.

Before rendering, Heyaa validates downloaded files with ffprobe to ensure each
required file exists, has a positive duration, and contains the expected stream.
Rendering does not start if required media validation fails.

Expected filenames are input/test_video.mp4, input/phonk.mp3, and
input/reference.mp4. Each run writes its final render and agent report under `output/runs/<run-id>/`;
`output/latest` points to the most recent completed run. A compatibility copy is
also written to `output/final_phonk_20s.mp4` after successful full renders.

For local-file-only use, run:

    python3 src/agent_director.py
