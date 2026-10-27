# Run Heyaa from media links or local files

Heyaa accepts YouTube video pages and direct HTTPS media URLs for source footage,
the Phonk soundtrack, and an optional pacing reference. Local files remain supported.
Use media you own or have permission to download and reuse. Platform restrictions apply.

## Requirements

- Python 3.10+
- FFmpeg and ffprobe available on PATH
- yt-dlp for YouTube page URLs

Install yt-dlp in WSL:

    python3 -m pip install --user -U yt-dlp

## Run from WSL

From the repository root:

    python3 src/agent_director.py \
      --video-url 'https://www.youtube.com/watch?v=SOURCE_VIDEO_ID' \
      --music-url 'https://www.youtube.com/watch?v=PHONK_TRACK_ID' \
      --reference-url 'https://www.youtube.com/watch?v=REFERENCE_VIDEO_ID'

You can also supply direct HTTPS media URLs, for example a host-provided MP4 or
MP3 download URL:

    python3 src/agent_director.py \
      --video-url 'https://cdn.example.org/source.mp4' \
      --music-url 'https://cdn.example.org/track.mp3'

Direct downloads must respond with a media-compatible content type, are limited
to 2 GiB per file, and use network timeouts. A web page that merely displays a
video is not a direct media URL. If the host requires a login, cookies, or
specialized access, use a local file instead.

The reference is optional; omit --reference-url if you do not have one. You may
mix URLs with local files: if --video-url is omitted, input/test_video.mp4 must
already exist; if --music-url is omitted, input/phonk.mp3 must already exist.

YouTube downloads show live yt-dlp progress and use IPv4 to avoid networks
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
input/reference.mp4. The final render and agent report remain:
- output/final_phonk_20s.mp4
- output/agent_report.json

For local-file-only use, run:

    python3 src/agent_director.py
