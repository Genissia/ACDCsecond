#!/usr/bin/env python3
"""Thunder Canyon -- easy launcher.

The simplest way to render a video: just run this file (hit the green run
button in PyCharm, or `python main.py` in a terminal).

    * A file picker opens -> choose an audio file to visualize.
    * Cancel the picker    -> renders a short no-audio demo instead, so you
      can confirm everything works before pointing it at a real song.

Want full control (resolution, fps, lightning tuning)? Call the renderer
directly with flags -- see python/README.md:

    python python/render.py song.mp3 -o out.mp4 --width 1920 --height 1080
"""
from __future__ import annotations

import sys
from pathlib import Path

# render.py and its helpers (shaders.py, audio_features.py) live in python/.
# Put that folder on the import path so this launcher runs from the repo root.
PYTHON_DIR = Path(__file__).resolve().parent / "python"
sys.path.insert(0, str(PYTHON_DIR))

import render  # noqa: E402  (import intentionally follows the sys.path tweak)

# Extensions offered in the file picker -- ffmpeg can decode far more, so
# "All files" is always available too.
AUDIO_EXTS = "*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.opus *.webm *.mp4 *.mov *.mkv"


def pick_audio() -> str:
    """Ask the user for the audio file to visualize.

    Opens a graphical file picker and returns the chosen path, or "" if the
    user cancels (which means "render the demo"). On a machine with no GUI
    (a headless server, or a Python without tkinter) it falls back to a
    typed prompt so the launcher still works.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()                 # we want only the dialog, not a blank window
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            title="Choose an audio file  (Cancel = demo)",
            filetypes=[("Audio / video", AUDIO_EXTS), ("All files", "*.*")],
        )
        root.destroy()
        return path or ""
    except Exception:
        raw = input("Type or paste an audio file path (or press Enter for a demo): ")
        return raw.strip().strip('"').strip("'")


def main() -> None:
    # If any command-line flags were passed, behave exactly like render.py so
    # power users keep the full argument interface.
    if len(sys.argv) > 1:
        render.main()
        return

    print("Thunder Canyon -- offline renderer")
    print("A file picker will open: choose an audio file, or Cancel for a demo.\n")

    audio = pick_audio()
    if audio:
        print(f"  audio:  {audio}")
        default_out = Path(audio).with_suffix(".mp4").name  # song.mp3 -> song.mp4
    else:
        print("  no file chosen -> rendering a demo")
        default_out = "demo.mp4"

    raw = input(f"Save video as [{default_out}]: ").strip().strip('"').strip("'")
    output = raw or default_out
    print()

    argv = [audio, "-o", output] if audio else ["--demo", "-o", output]
    sys.argv = [sys.argv[0], *argv]
    render.main()


if __name__ == "__main__":
    main()
