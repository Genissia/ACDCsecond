# Thunder Canyon — Python offline renderer

A standalone command-line version of `../index.html`: same raymarched,
cel-shaded canyon + storm shader, same audio-reactive design, rendered to an
`.mp4` file instead of a browser canvas. Built for machines with a real GPU
where it renders far faster than the in-browser recorder, and for
batch/headless use (servers, CI, etc.).

## Setup

```bash
pip install -r requirements.txt
# needs ffmpeg on PATH (falls back to the bundled imageio-ffmpeg binary if absent)
```

## Usage

```bash
python3 render.py song.mp3 -o out.mp4
python3 render.py song.mp3 -o out.mp4 --width 1920 --height 1080 --fps 60
python3 render.py --demo -o demo.mp4 --seconds 20     # no audio file needed
```

Any container **ffmpeg** can decode works as input — mp3, wav, m4a, flac,
mpeg, mp4, mov, etc. Decoding is delegated to ffmpeg itself (`audio_features.
decode_to_wav`), not to a filename-extension guess, so a misnamed file (audio
saved with a `.mpeg` extension, for example) or even a real video file with an
audio track both work.

### Key flags

| Flag | Meaning |
|---|---|
| `--width/--height/--fps` | output resolution & frame rate |
| `--intensity` | percentile (0-100, default 82) — how selective lightning is. Only onsets in the top `(100-intensity)`% of the **whole song's** energy trigger a strike. Raise for fewer/bigger-only moments, lower for more frequent ones. |
| `--refractory` | minimum seconds between strikes (default 0.4) |
| `--list-strikes` | print detected strike timestamps for tuning |
| `--gl-backend` | moderngl backend override (`egl`, `glx`, ...). `auto` tries a normal context first, falls back to `egl` — useful on headless Linux boxes. |
| `--crf` / `--preset` | x264 quality/speed knobs |

## How it works

1. **`audio_features.py`** — decodes the input via ffmpeg to a canonical
   mono WAV, computes an STFT, and derives:
   - smoothed low/mid/high band envelopes (mirrors the browser's
     `AnalyserNode` bands) → drive mountain size (`uLow`) and crest
     detail/melody (`uMid`) in the shader.
   - a broadband onset curve, peak-picked with librosa's standard
     adaptive algorithm, **then filtered to a global percentile of the
     whole song** — this is what keeps lightning to genuinely intense
     moments instead of firing on every riff note (a live/causal detector,
     like the browser's, can't see the whole song in advance and is
     inherently less selective).
2. **`shaders.py`** — the exact same GLSL raymarching shader as
   `index.html`, ported to desktop GLSL 330 (`gl_FragColor` → `out
   fragColor`, `attribute`/`varying` → `in`/`out`). Tune the *look* in one
   place and port the change to the other by hand — there's no shared
   build step.
3. **`render.py`** — opens a headless OpenGL context (moderngl), renders
   one frame per audio-frame with the extracted features as uniforms, and
   pipes raw RGB frames straight into a single ffmpeg process that muxes
   them against the original audio track (`-shortest`, H.264 + AAC).

## Headless Linux setup (servers / CI)

If you hit `XOpenDisplay`/`libEGL.so not loaded` errors creating the GL
context, install Mesa's software renderer once:

```bash
apt-get install -y libegl1 libgl1-mesa-dri libglx-mesa0
```

then pass `--gl-backend egl` explicitly. On a machine with a real GPU and
drivers, no extra setup is normally needed — `--gl-backend auto` (the
default) finds it.

## Differences from the browser app

- No live interactivity (no drag-drop, no play/pause) — it's a batch
  renderer, by design.
- Lightning selectivity can be smarter here: it sees the whole song up
  front, so `--intensity` is a genuine "top N% of the entire track" gate,
  not just a recent-history heuristic.
- Same visual language, ported by hand — if you tune `shaders.py`, mirror
  the change in `../index.html`'s `<script id="fs">` (or vice versa).
