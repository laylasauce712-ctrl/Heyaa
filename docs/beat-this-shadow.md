# Beat This! shadow integration

## Upstream

- Project: CPJKU/beat_this
- Distribution: beat-this 1.1.0
- License: MIT (published code and published model weights)
- Model used by Heyaa: small0 (~8.1 MB per upstream README)
- Runtime: PyTorch 2+ and torchaudio, plus the packages declared upstream
- Inference: CPU-only in this first integration; CUDA is deliberately not assumed.

The model returns timestamped beat and downbeat predictions. This is stronger
musical evidence than the current FFmpeg bass-onset/periodic-grid heuristic,
but it is not a semantic drop detector and it cannot determine the best edit
moment by itself.

## Isolation and execution

The optional runtime is installed only in tools/beat-analysis/.venv:
- PyTorch and torchaudio are installed from the official CPU wheel index.
- beat-this is pinned to 1.1.0 in requirements-beats.txt.
- The core Heyaa Python runtime does not import torch, torchaudio, or soundfile.
- `soundfile` is installed for the upstream audio-loading fallback; this avoids
  requiring TorchCodec just to open the worker's generated WAV audio.
- The worker extracts at most 45 seconds of mono 22.05 kHz audio with FFmpeg.
- The model checkpoint is small0; first use may download its published weights
  into the isolated user's PyTorch cache.
- The process is bounded by a worker timeout. A worker failure records evidence
  and never blocks the normal render.

## Shadow-only policy

The existing FFmpeg bass/onset heuristic remains the only source used for EDL
timing, drop-freeze placement, flashes and other production decisions.
Beat This! events are logged as observations and compared with heuristic beat
candidates within a 100ms one-to-one tolerance. Downbeats are counted and
recorded separately; the old onset heuristic is not mislabelled as a downbeat
detector. Neither method is treated as ground truth.

Do not promote Beat This! into production timing until it has been compared
against representative Phonk/Montagem soundtracks and its beat/downbeat
alignment, CPU time, memory use and failure behaviour have been reviewed.

Remove only tools/beat-analysis/.venv to disable the observer. This does not
touch tools/realesrgan or tools/scene-analysis.
