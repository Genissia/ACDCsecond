# Thunder Canyon

An **audio-reactive music-video visualizer**. A POV camera flies through a
narrow, winding canyon; the mountains breathe and grow with the beat and
melody, and **lightning cracks across the storm sky on the heavy hits** — a
stylized, cel-shaded, deliberately non-photorealistic look built to visualize
AC/DC's *Thunderstruck* (but it works on any song).

It renders a raymarched GLSL scene frame-by-frame under real audio analysis
(`librosa` / `numpy`) and muxes the result into an `.mp4` with ffmpeg. It runs
headless, needs no browser, and reads virtually any audio (or video) file that
ffmpeg can decode.

![still](docs/still.png)

---

## What you need to run it

Before anything else, a new machine needs these three things:

| Requirement | Details |
|---|---|
| **Python 3.11** | 3.11 is the safe choice — it has prebuilt wheels for every dependency. 3.10–3.12 also work. **Avoid 3.13** on Windows: `pip` will try to compile the GL dependency from source and demand the Visual C++ Build Tools. |
| **A working OpenGL 3.3 context** | Any machine with a real GPU + drivers works out of the box. On a headless Linux server with no GPU you can still render using Mesa's software renderer (see [Headless Linux](#headless-linux-servers--ci) below). |
| **ffmpeg** *(optional)* | Used for encoding. If it isn't on your `PATH`, the bundled `imageio-ffmpeg` binary is used automatically — so you don't strictly need a system ffmpeg. |

Everything else is a `pip` package installed in the setup step below
(`numpy`, `librosa`, `soundfile`, `moderngl`, `imageio-ffmpeg`).

> **No audio file is required to test.** You can render a built-in demo with a
> synthetic beat to confirm your setup works before pointing it at a real song.

---

## First-time setup

From the repository root, install the Python packages once:

```bash
pip install -r python/requirements.txt
```

Using a virtual environment is recommended:

```bash
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r python/requirements.txt
```

---

## How to run it

### The easy way

Run `main.py` (hit the green ▶ in PyCharm, or from a terminal):

```bash
python main.py
```

- **A file picker opens** → choose an audio file and it renders that track to
  an `.mp4` next to it.
- **Hit Cancel instead** → it renders a short no-audio demo, so you can confirm
  everything is set up before pointing it at a real song.

On a headless machine with no GUI, the picker falls back to a typed prompt, so
`main.py` still works over SSH.

### Full control (the renderer directly)

`main.py` is a thin launcher over `python/render.py`, which exposes every flag —
resolution, frame rate, and lightning tuning:

```bash
# render a song at 1080p60
python python/render.py song.mp3 -o out.mp4 --width 1920 --height 1080 --fps 60

# render a 20-second demo, no audio file needed
python python/render.py --demo -o demo.mp4 --seconds 20
```

### Flags

| Flag | Meaning |
|---|---|
| `-o, --output` | output video path (`.mp4`) — **required** |
| `--width` / `--height` / `--fps` | output resolution & frame rate (default `1280×720 @ 30`) |
| `--intensity` | percentile `0–100` (default `82`) — how selective lightning is. Only onsets in the top `(100−intensity)`% of the **whole song's** energy fire a strike. Raise for fewer, bigger-only moments; lower for more frequent ones. |
| `--refractory` | minimum seconds between strikes (default `0.4`) |
| `--strikes-file` | a file of explicit strike times (seconds or `m:ss`, one per line) that force a full-strength bolt — e.g. every "Thunder!". See `thunder_strikes.txt`. |
| `--strikes-only` | fire lightning **only** at `--strikes-file` times, ignoring auto-detection |
| `--list-strikes` | print the detected strike timestamps and exit (handy for tuning) |
| `--gl-backend` | moderngl backend override (`egl`, `glx`, …). `auto` (default) tries a normal context, then falls back to `egl` — useful on headless Linux. |
| `--crf` / `--preset` | x264 quality / speed knobs (default `18` / `medium`) |
| `--demo` | render a synthetic beat, no audio file needed |
| `--seconds` | duration for `--demo` mode |

### Audio formats

Any container **ffmpeg** can decode: `.mp3`, `.wav`, `.m4a`/`.aac`, `.flac`,
`.ogg`, `.opus`, `.webm`, and even a real video file with an audio track.
Decoding is delegated to ffmpeg itself, not to a filename guess, so a misnamed
file (audio saved with a `.mpeg` extension, say) works too.

---

## Headless Linux (servers / CI)

On a machine with a real GPU and drivers, no extra setup is needed —
`--gl-backend auto` finds it. If you hit `XOpenDisplay` or
`libEGL.so not loaded` errors while creating the GL context, install Mesa's
software renderer once and pass the backend explicitly:

```bash
apt-get install -y libegl1 libgl1-mesa-dri libglx-mesa0
python python/render.py song.mp3 -o out.mp4 --gl-backend egl
```

---

## How it works

The renderer decodes the track, runs an STFT, and derives:

- **low / mid / high** band envelopes — a three-way frequency split. Bass
  (`uLow`) scales the overall mountain height/size (they *breathe* and grow on
  the beat); mids (`uMid`) drive ridge/crest detail (the melody).
- a **lightning trigger** — a broadband onset curve, peak-picked with librosa's
  adaptive algorithm, then filtered to a global percentile of the *whole song's*
  energy, so only moments that are genuinely loud *for the song* fire a strike.
  A refractory period keeps strikes as discrete moments. Because it sees the
  whole song up front, `--intensity` is a real "top N% of the entire track"
  gate — not a recent-history heuristic.

The GLSL raymarching shader (`python/shaders.py`, desktop GLSL 330) draws a
cel-shaded height-field canyon with ridged-noise crestlines, a limited stormy
palette, aerial fog, vignette and faint scanlines. On each strike a jagged,
branching bolt is drawn in the sky, the clouds light up, and the canyon floods
with cold light. Tuning knobs (palette, wall steepness, fog, `halfW` canyon
width) live at the top of that file — there's no build step.

`render.py` opens a headless OpenGL context (moderngl), renders one frame per
audio-frame with the extracted features as uniforms, and pipes raw RGB frames
straight into a single ffmpeg process that muxes them against the original
audio (`-shortest`, H.264 + AAC).

This is genuinely audio-reactive, not hardcoded to one song — it analyzes
whatever file you give it.

---

## Project layout

```
main.py                  easy launcher (file picker → render.py)
thunder_strikes.txt      example --strikes-file for AC/DC "Thunderstruck"
python/
  render.py              frame loop + ffmpeg mux + CLI
  audio_features.py      ffmpeg decode + STFT + band/onset analysis
  shaders.py             the GLSL raymarching shader (tune the look here)
  requirements.txt       pip dependencies
  README.md              deeper notes on the renderer internals
docs/still.png           preview still
```

See **[`python/README.md`](python/README.md)** for deeper notes on the renderer.

## Notes

- **Audio is not committed.** `assets/*` audio and `renders/*` are git-ignored:
  the visualizer is BYO-audio, and copyrighted tracks stay local.
- It's a batch renderer by design — no live playback or interactivity.
