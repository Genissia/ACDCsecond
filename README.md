# Genny — Thunder Canyon

An audio-reactive **music-video visualizer**. A POV camera drives through a
narrow, winding canyon; the mountains breathe with the beat and melody, and
**lightning cracks across the storm sky on the heavy hits** — a stylized,
cel-shaded, non-photorealistic look built to visualize AC/DC's *Thunderstruck*.

It renders a raymarched GLSL scene frame-by-frame under real audio analysis
(`librosa` / `numpy`) and muxes the result into an `.mp4` with ffmpeg — no
browser, works headless, and reads virtually any audio (or video) file that
ffmpeg can decode.

![still](docs/still.png)

## Run it

The easy way — run `main.py` and answer the two prompts (hit the green ▶ in
PyCharm, or from a terminal):

```
python main.py
```

- **Give it an audio file** when prompted → it renders that track into a video.
- **Press Enter with no file** → it renders a short no-audio demo, so you can
  confirm everything is set up before pointing it at a real song.

### First-time setup

Install the project's Python packages once, from the repo root:

```
pip install -r python/requirements.txt
```

> **Windows note:** use a Python version that has prebuilt wheels for the GL
> dependency — **Python 3.11** is the safe choice. On Python 3.13, `pip` tries
> to compile `glcontext` from source and needs the Visual C++ Build Tools.
> ffmpeg is used for encoding; if it isn't on your PATH the bundled
> `imageio-ffmpeg` binary is used automatically.

### More control (optional)

`main.py` is a thin launcher over `python/render.py`, which exposes the full
set of flags — resolution, frame rate, lightning tuning, and more:

```
python python/render.py song.mp3 -o out.mp4 --width 1920 --height 1080 --fps 60
python python/render.py --demo -o demo.mp4 --seconds 20
```

See **[`python/README.md`](python/README.md)** for every flag and how the
audio analysis works.

### Audio formats
Any container **ffmpeg** can decode: `.mp3`, `.wav`, `.m4a`/`.aac`, `.flac`,
`.ogg`, `.opus`, `.webm`, and even a real video file with an audio track.
Decoding is delegated to ffmpeg itself, not to a filename guess, so a misnamed
file (audio saved with a `.mpeg` extension, say) works too.

## How it maps to the brief

| Requirement | Implementation |
|---|---|
| POV camera "driving" through a narrow canyon | Fragment-shader raymarched height-field. The camera follows a winding path (`pathX`) down a narrow gap between two walls, moving forward every frame. |
| Mountains shift up/down & in size to beat + melody | Bass energy (`uLow`) scales overall mountain height/size (they *breathe* & grow on the beat); mids (`uMid`) drive the ridge/crest detail (the melody). |
| Lightning on the intense beats ("Thunder") | A broadband onset detector fires a flash envelope (`uBeat`); on each strike a jagged, branching bolt is drawn in the sky, the clouds light up, and the canyon floods with cold light. |
| Stylized, non-photoreal, but clearly mountains + lightning | Posterized **cel shading**, ridged-noise crestlines, a limited stormy blue palette, aerial fog, vignette and faint scanlines. Readable as canyon + lightning, deliberately not photorealistic. |

### Audio → visuals (signal flow)
The renderer decodes the track, runs an STFT, and derives:
- **low / mid / high** band envelopes → shader uniforms driving mountain
  size, crest detail and shimmer.
- a **lightning trigger** — a broadband onset curve, peak-picked and then
  filtered to a global percentile of the *whole song's* energy, so only
  moments that are genuinely loud *for the song* fire a strike. A refractory
  period keeps strikes as discrete moments.

Tuning knobs live at the top of the fragment shader in `python/shaders.py`
(palette, wall steepness, fog, `halfW` canyon width) and in the analysis
options exposed as the `--intensity` / `--refractory` flags.

This is genuinely audio-reactive, not hardcoded to this song — it analyzes
whatever file you give it, so it works the same way on the full track, a
different section, or an entirely different song.

## Notes
- **Audio is not committed.** `assets/*` audio and `renders/*` are git-ignored:
  the visualizer is BYO-audio, and copyrighted tracks stay local.
- The whole renderer is a handful of small files in [`python/`](python/) —
  `main.py` launches `render.py` (the frame loop + ffmpeg mux), which uses
  `audio_features.py` (analysis) and `shaders.py` (the GLSL).
