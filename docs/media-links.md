# Run Heyaa from YouTube media links

Heyaa accepts a YouTube video URL for source footage, another YouTube video URL
for the Phonk soundtrack, and an optional YouTube video URL as a pacing reference.
Use media you own or have permission to download and reuse. Availability and
platform restrictions still apply.

## Requirements

- Python 3.10+
- FFmpeg and ffprobe available on PATH
- yt-dlp available on PATH

Install yt-dlp in WSL:

    python3 -m pip install --user -U yt-dlp

## Run from WSL

From the repository root:

    python3 src/agent_director.py \
      --video-url 'https://www.youtube.com/watch?v=SOURCE_VIDEO_ID' \
      --music-url 'https://www.youtube.com/watch?v=PHONK_TRACK_ID' \
      --reference-url 'https://www.youtube.com/watch?v=REFERENCE_VIDEO_ID'

The reference is optional; omit --reference-url if you do not have one. You may
mix URLs with local files: if --video-url is omitted, input/test_video.mp4 must
already exist; if --music-url is omitted, input/phonk.mp3 must already exist.

Before rendering, Heyaa validates supplied links as single YouTube video URLs,
downloads them into input/, then uses ffprobe to verify that each required file
exists, has a positive duration, and contains the expected video or audio stream.
Rendering does not start if required media validation fails. Playlists and
non-YouTube URLs are intentionally rejected.

Expected downloaded filenames are input/test_video.mp4, input/phonk.mp3, and
input/reference.mp4. The final render and agent report remain:
- output/final_phonk_20s.mp4
- output/agent_report.json

For local-file-only use, the existing command remains python3 src/agent_director.py.
