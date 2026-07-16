#!/usr/bin/env python3
"""Thunder Canyon -- standalone Python/OpenGL renderer.

A raymarched, cel-shaded canyon + storm shader driven by real audio analysis
(see audio_features.py). Renders frame-by-frame through moderngl (real GPU if
available) and muxes the result with the source audio via ffmpeg in one pass.

Usage:
    python3 render.py song.mp3 -o out.mp4
    python3 render.py song.mp3 -o out.mp4 --width 1920 --height 1080 --fps 60
    python3 render.py --demo -o demo.mp4 --seconds 20   # no audio file needed

Any container ffmpeg can decode works as input (mp3, wav, m4a, mpeg, mp4,
mov, ...) -- decoding is delegated to ffmpeg itself, not to a codec guess.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import moderngl
import numpy as np

from shaders import FRAGMENT_SRC, VERTEX_SRC
from audio_features import (extract_features, Features, find_ffmpeg,
                             load_strikes_file, _spike_envelope)


def synthetic_features(fps: int, seconds: float) -> Features:
    """Demo driving signal (no audio) -- a synthetic beat so the scene is alive."""
    frames = int(seconds * fps)
    t = np.arange(frames) / fps
    bpm = 118.0
    beat_t = 60.0 / bpm
    phase = (t % beat_t) / beat_t
    env = (1 - phase) ** 3
    low = env * (0.6 + 0.4 * np.sin(t * 0.7))
    mid = 0.25 + 0.22 * np.sin(t * 2.1) + 0.15 * np.sin(t * 5.3)
    high = 0.15 + 0.15 * np.abs(np.sin(t * 7.0))

    rng = np.random.default_rng(0)
    beat = np.zeros(frames)
    seed = np.zeros(frames)
    strike_idx = []
    last_beat = -999.0
    cur_seed = rng.random() * 100
    for i in range(frames):
        if t[i] - last_beat > 0.6 and phase[i] < 1.0 / fps * 2:
            beat[i] = 1.0
            strike_idx.append(i)
            cur_seed = rng.random() * 100
            last_beat = t[i]
        seed[i] = cur_seed
    decay = 0.04 ** (1.0 / fps)
    for i in range(1, frames):
        d = beat[i - 1] * decay
        if d > beat[i]:
            beat[i] = d

    # slow structural energy: a synthetic build/drop wave (0..1)
    energy = np.clip(0.45 + 0.4 * np.sin(t * 0.22), 0.0, 1.0)
    # tempo-synced throb on the demo's beat grid
    pulse = np.zeros(frames)
    pulse_decay = 0.12 ** (1.0 / max(1, int(0.30 * fps)))
    beat_hit = phase < 1.0 / fps * 2
    pulse[beat_hit] = 1.0
    for i in range(1, frames):
        d = pulse[i - 1] * pulse_decay
        if d > pulse[i]:
            pulse[i] = d

    spike = _spike_envelope(frames, [(i, 1.0) for i in strike_idx], fps)

    # camera rides the rhythm (see extract_features): cruise + beat surge + hit lunge
    speed = 2.6 + low * 3.0 + pulse * 2.4 + beat * 3.5
    speed *= 0.85 + 0.4 * energy
    move = np.cumsum(speed / fps)
    return Features(fps=fps, duration=seconds, frames=frames, low=low, mid=mid,
                     high=high, beat=beat, seed=seed, move=move,
                     energy=energy, pulse=pulse, spike=spike, strike_times=[])


def make_context(backend: str | None):
    if backend and backend != "auto":
        return moderngl.create_context(standalone=True, backend=backend)
    try:
        return moderngl.create_context(standalone=True)
    except Exception:
        return moderngl.create_context(standalone=True, backend="egl")


def render(args: argparse.Namespace) -> None:
    fps, w, h = args.fps, args.width, args.height

    if args.demo:
        feat = synthetic_features(fps, args.seconds)
        audio_for_mux = None
    else:
        forced = load_strikes_file(args.strikes_file) if args.strikes_file else None
        if forced:
            print(f"forcing {len(forced)} strike(s) from {args.strikes_file}"
                  + (" (strikes-only)" if args.strikes_only else ""))
        print(f"analyzing audio: {args.audio} ...")
        feat = extract_features(
            args.audio, fps=fps,
            intensity_percentile=args.intensity,
            refractory_sec=args.refractory,
            forced_strikes=forced,
            strikes_only=args.strikes_only,
        )
        audio_for_mux = args.audio
        print(f"  duration {feat.duration:.1f}s, {feat.frames} frames, "
              f"{len(feat.strike_times)} lightning strikes "
              f"({len(feat.strike_times)/max(feat.duration,1e-6):.2f}/s)")
        if args.list_strikes:
            print("  strike times (s):", [round(x, 2) for x in feat.strike_times])

    ctx = make_context(args.gl_backend)
    prog = ctx.program(vertex_shader=VERTEX_SRC, fragment_shader=FRAGMENT_SRC)
    vbo = ctx.buffer(np.array([-1, -1, 3, -1, -1, 3], dtype="f4").tobytes())
    vao = ctx.simple_vertex_array(prog, vbo, "aPos")
    fbo = ctx.framebuffer(color_attachments=[ctx.texture((w, h), 4)])
    fbo.use()

    # some uniforms (currently uHigh) are declared but unused by the shader math
    # and get optimized out by the GLSL compiler -- guard every lookup.
    U = {name: prog.get(name, None) for name in
         ("uRes", "uTime", "uMove", "uLow", "uMid", "uHigh", "uBeat", "uSeed",
          "uEnergy", "uPulse", "uSpike")}
    if U["uRes"] is not None:
        U["uRes"].value = (float(w), float(h))

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_ffmpeg()
    cmd = [
        ffmpeg, "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps),
        "-i", "pipe:0",
    ]
    if audio_for_mux:
        cmd += ["-i", audio_for_mux, "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", str(args.crf),
            "-preset", args.preset, "-shortest", str(out_path)]

    print("encoding:", " ".join(cmd))
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    # Drain ffmpeg's stderr on a background thread. ffmpeg writes progress to
    # stderr the whole time; if we only read it at the end, its pipe buffer
    # fills on a long render, ffmpeg blocks writing to it, stops reading our
    # video frames, and the whole pipeline deadlocks. Reading it continuously
    # keeps frames flowing while still capturing the log for error reporting.
    err_chunks: list[bytes] = []
    err_thread = threading.Thread(
        target=lambda: err_chunks.extend(iter(lambda: proc.stderr.read(4096), b"")),
        daemon=True,
    )
    err_thread.start()

    t0 = time.time()
    try:
        frame_vals = {
            "uTime": lambda i: i / fps,
            "uMove": lambda i: feat.move[i],
            "uLow": lambda i: feat.low[i],
            "uMid": lambda i: feat.mid[i],
            "uHigh": lambda i: feat.high[i],
            "uBeat": lambda i: feat.beat[i],
            "uSeed": lambda i: feat.seed[i],
            "uEnergy": lambda i: feat.energy[i],
            "uPulse": lambda i: feat.pulse[i],
            "uSpike": lambda i: feat.spike[i],
        }
        for i in range(feat.frames):
            fbo.clear()
            for name, fn in frame_vals.items():
                if U[name] is not None:
                    U[name].value = float(fn(i))
            vao.render(moderngl.TRIANGLES)

            data = fbo.read(components=3, alignment=1)
            frame = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 3)[::-1]
            proc.stdin.write(frame.tobytes())

            if i % 60 == 0:
                el = time.time() - t0
                r = i / el if el > 0 else 0
                print(f"  frame {i}/{feat.frames}  {el:.0f}s  {r:.1f} fps", flush=True)
    finally:
        proc.stdin.close()
        ret = proc.wait()
        err_thread.join()
        if ret != 0:
            sys.stderr.write(b"".join(err_chunks).decode(errors="replace"))
            raise RuntimeError(f"ffmpeg exited {ret}")

    print(f"done: {out_path}  ({time.time()-t0:.0f}s)")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("audio", nargs="?", help="input audio/video file (any ffmpeg-readable format)")
    p.add_argument("-o", "--output", required=True, help="output video path (.mp4)")
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=720)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--crf", type=int, default=18, help="x264 quality (lower = better, 18 is visually lossless-ish)")
    p.add_argument("--preset", default="medium", help="x264 speed/quality preset")
    p.add_argument("--intensity", type=float, default=82.0,
                    help="percentile (0-100): how selective lightning is. Higher = fewer, bigger-only strikes.")
    p.add_argument("--refractory", type=float, default=0.4, help="minimum seconds between strikes")
    p.add_argument("--strikes-file", help="file of strike times (seconds or m:ss, one per "
                    "line) that force a full-strength bolt -- e.g. every \"Thunder!\"")
    p.add_argument("--strikes-only", action="store_true",
                    help="fire lightning ONLY at --strikes-file times (ignore auto-detected strikes)")
    p.add_argument("--list-strikes", action="store_true", help="print detected strike timestamps")
    p.add_argument("--gl-backend", default="auto", help="moderngl backend override, e.g. egl, glx (default: auto)")
    p.add_argument("--demo", action="store_true", help="render with a synthetic beat, no audio file needed")
    p.add_argument("--seconds", type=float, default=20.0, help="duration for --demo mode")
    args = p.parse_args()

    if not args.demo and not args.audio:
        p.error("an audio file is required unless --demo is given")
    if args.strikes_only and not args.strikes_file:
        p.error("--strikes-only needs --strikes-file")
    if args.strikes_file and args.demo:
        print("note: --strikes-file is ignored in --demo mode")
    if args.audio and not shutil.which("ffmpeg") and Path(args.audio).suffix.lower() not in (".wav",):
        print("warning: system ffmpeg not found on PATH, falling back to imageio-ffmpeg's bundled binary")

    render(args)


if __name__ == "__main__":
    main()
