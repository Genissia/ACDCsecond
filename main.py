#!/usr/bin/env python3
"""Thunder Canyon -- easy launcher.

The simplest way to render a video: just run this file (hit the green run
button in PyCharm, or `python main.py` in a terminal) and answer the two
prompts.

    * Give it an audio file  -> renders that track into a video.
    * Leave the audio empty   -> renders a short no-audio demo instead, so
      you can confirm everything works.

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


def ask(prompt: str, default: str = "") -> str:
    """Prompt for input; strip whitespace and the quotes drag-and-drop adds."""
    suffix = f" [{default}]" if default else ""
    val = input(f"{prompt}{suffix}: ").strip().strip('"').strip("'")
    return val or default


def main() -> None:
    # If any command-line flags were passed, behave exactly like render.py so
    # power users keep the full argument interface.
    if len(sys.argv) > 1:
        render.main()
        return

    print("Thunder Canyon -- offline renderer")
    print("Drag an audio file in for its path, or press Enter for a demo.\n")

    audio = ask("Audio file to visualize")
    output = ask("Save video as", "out.mp4")
    print()

    argv = [audio, "-o", output] if audio else ["--demo", "-o", output]
    sys.argv = [sys.argv[0], *argv]
    render.main()


if __name__ == "__main__":
    main()
