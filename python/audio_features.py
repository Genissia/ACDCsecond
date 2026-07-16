"""Audio -> per-video-frame feature extraction for the Thunder Canyon renderer.

Signal flow: band energies drive the mountains, a broadband onset drives the
lightning. Being fully offline (it can see the whole song up front), it uses a
non-causal approach that a live/streaming detector can't:

  - librosa's standard adaptive peak-picker replaces the hand-rolled local
    threshold (proper, well-tested onset/beat literature algorithm).
  - a GLOBAL percentile gate on top of that keeps only moments that are
    genuinely loud for the *whole song*, not just relative to a recent
    quiet passage -- this is what keeps lightning off of "every riff hit".

Any container ffmpeg can demux/decode works as input (mp3, wav, mpeg, mp4,
mov, ...) because decoding is done by shelling out to ffmpeg first, rather
than relying on a media library's format guessing.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
import librosa

try:
    import imageio_ffmpeg
except ImportError:  # pragma: no cover - optional fallback
    imageio_ffmpeg = None

SR = 44100  # canonical analysis sample rate

# Hz ranges for the three bands (low = bass/kick, mid = riffs, high = cymbals)
LOW_HZ = (20, 320)
MID_HZ = (320, 2000)
HIGH_HZ = (2000, 6500)

# broadband onset weights -- mids weighted highest (riffs & chant vocals live here)
ONSET_WEIGHTS = (0.45, 0.95, 0.35)  # low, mid, high

ENV_ATTACK = 0.5   # per-frame envelope-follower attack (rising)
ENV_RELEASE = 0.06  # per-frame envelope-follower release (falling)

FLASH_DECAY_PER_SEC = 0.04  # flash envelope decays to 4% of its value each second


def find_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    if imageio_ffmpeg is not None:
        return imageio_ffmpeg.get_ffmpeg_exe()
    raise RuntimeError(
        "No ffmpeg found (system PATH or imageio-ffmpeg). "
        "Install ffmpeg or `pip install imageio-ffmpeg`."
    )


def decode_to_wav(input_path: str, sr: int = SR) -> str:
    """Decode ANY ffmpeg-readable file (mp3/wav/mpeg/mp4/mov/...) to a mono WAV.

    Returns a path to a temp file the caller should delete when done.
    """
    ffmpeg = find_ffmpeg()
    out = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    out.close()
    cmd = [
        ffmpeg, "-y", "-i", str(input_path),
        "-vn", "-ac", "1", "-ar", str(sr),
        "-f", "wav", out.name,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        Path(out.name).unlink(missing_ok=True)
        raise RuntimeError(
            f"ffmpeg couldn't decode {input_path!r} as audio:\n{proc.stderr[-2000:]}"
        )
    return out.name


def _band_bins(freqs: np.ndarray, lo_hz: float, hi_hz: float) -> tuple[int, int]:
    lo = int(np.searchsorted(freqs, lo_hz))
    hi = int(np.searchsorted(freqs, hi_hz))
    return max(1, lo), max(lo + 1, hi)


def _pct_norm(x: np.ndarray, pct: float = 97.0, target: float = 0.85) -> np.ndarray:
    ref = np.percentile(x, pct)
    if ref <= 1e-9:
        return np.zeros_like(x)
    return np.clip(x * (target / ref), 0.0, 1.0)


def _envelope_follow(x: np.ndarray) -> np.ndarray:
    out = np.empty_like(x)
    s = 0.0
    for i, v in enumerate(x):
        rate = ENV_ATTACK if v > s else ENV_RELEASE
        s += (v - s) * rate
        out[i] = s
    return out


def _moving_avg(x: np.ndarray, win: int) -> np.ndarray:
    """Slow smoother for the structural energy envelope (verse vs chorus)."""
    win = max(1, int(win))
    if win <= 1:
        return x
    k = np.ones(win) / win
    return np.convolve(x, k, mode="same")


@dataclass
class Features:
    fps: int
    duration: float
    frames: int
    low: np.ndarray    # 0..1, smoothed
    mid: np.ndarray    # 0..1, smoothed
    high: np.ndarray   # 0..1, smoothed
    beat: np.ndarray   # 0..1, decaying flash env -- peak height = strike strength
    seed: np.ndarray   # per-frame random seed (changes on each strike)
    move: np.ndarray   # cumulative camera travel distance
    energy: np.ndarray # 0..1, slow overall loudness (song structure)
    pulse: np.ndarray  # 0..1, tempo-synced throb (retriggered each beat)
    strike_times: list[float]


def extract_features(
    audio_path: str,
    fps: int = 30,
    intensity_percentile: float = 82.0,
    refractory_sec: float = 0.4,
    rng: np.random.Generator | None = None,
) -> Features:
    """Analyze an audio file and produce per-video-frame driving signals.

    intensity_percentile: how selective the lightning is -- only onsets in
      the top (100 - intensity_percentile)% of the *whole song's* energy
      trigger a strike. Raise it for fewer, bigger moments; lower it for
      more frequent strikes.
    refractory_sec: minimum gap between strikes.
    """
    rng = rng or np.random.default_rng()

    wav_path = decode_to_wav(audio_path)
    try:
        y, sr = sf.read(wav_path, dtype="float32", always_2d=False)
    finally:
        Path(wav_path).unlink(missing_ok=True)
    if y.ndim > 1:
        y = y.mean(axis=1)

    duration = len(y) / sr
    frames = max(1, int(np.floor(duration * fps)))
    hop = int(round(sr / fps))
    n_fft = 2048

    S = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=hop, win_length=n_fft,
                             window="hann", center=True))
    S = S[:, :frames]
    if S.shape[1] < frames:
        S = np.pad(S, ((0, 0), (0, frames - S.shape[1])))

    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    lo_b = _band_bins(freqs, *LOW_HZ)
    mid_b = _band_bins(freqs, *MID_HZ)
    hi_b = _band_bins(freqs, *HIGH_HZ)

    raw_low = S[lo_b[0]:lo_b[1]].mean(axis=0)
    raw_mid = S[mid_b[0]:mid_b[1]].mean(axis=0)
    raw_high = S[hi_b[0]:hi_b[1]].mean(axis=0)

    low = _envelope_follow(_pct_norm(raw_low))
    mid = _envelope_follow(_pct_norm(raw_mid))
    high = _envelope_follow(_pct_norm(raw_high))

    w_lo, w_mid, w_hi = ONSET_WEIGHTS
    onset = w_lo * _pct_norm(raw_low) + w_mid * _pct_norm(raw_mid) + w_hi * _pct_norm(raw_high)

    # local adaptive peaks (proper onset/beat literature algorithm)
    win = max(1, int(round(0.7 * fps)))
    wait = max(1, int(round(refractory_sec * fps)))
    peaks = librosa.util.peak_pick(
        onset, pre_max=win, post_max=win, pre_avg=win, post_avg=win,
        delta=0.06, wait=wait,
    )

    # global gate: only keep peaks that are loud for the WHOLE song
    if len(peaks) and intensity_percentile > 0:
        gate = np.percentile(onset, intensity_percentile)
        peaks = peaks[onset[peaks] >= gate]

    strike_times = [float(p / fps) for p in peaks]

    # per-strike STRENGTH: scale each flash by how hard that onset hit, mapped
    # so even light strikes still flash (0.55) and the biggest reach 1.0.
    beat = np.zeros(frames, dtype=np.float64)
    if len(peaks):
        pk = onset[peaks]
        norm = pk / (pk.max() + 1e-9)
        beat[peaks] = 0.55 + 0.45 * norm
    decay_per_frame = FLASH_DECAY_PER_SEC ** (1.0 / fps)
    for i in range(1, frames):
        d = beat[i - 1] * decay_per_frame
        if d > beat[i]:
            beat[i] = d

    # slow loudness envelope (RMS) -> canyon width & fog: quiet = wide+foggy,
    # loud = narrow+clear. Smoothed over ~1s so it tracks song sections.
    rms = librosa.feature.rms(y=y, frame_length=n_fft, hop_length=hop, center=True)[0]
    rms = rms[:frames]
    if len(rms) < frames:
        rms = np.pad(rms, (0, frames - len(rms)))
    energy = np.clip(_moving_avg(_pct_norm(rms, pct=95, target=1.0), win=fps), 0.0, 1.0)

    # tempo-synced PULSE: a gentle throb retriggered on every tracked beat, so
    # the scene breathes on the BPM even between lightning strikes.
    pulse = np.zeros(frames, dtype=np.float64)
    try:
        _, beat_frames = librosa.beat.beat_track(
            y=y, sr=sr, hop_length=hop, units="frames"
        )
        beat_frames = beat_frames[beat_frames < frames]
        pulse[beat_frames] = 1.0
    except Exception:
        beat_frames = np.array([], dtype=int)
    pulse_decay = 0.12 ** (1.0 / max(1, int(0.30 * fps)))  # ~decays over a beat
    for i in range(1, frames):
        d = pulse[i - 1] * pulse_decay
        if d > pulse[i]:
            pulse[i] = d

    seed = np.empty(frames, dtype=np.float64)
    current = rng.random() * 100.0
    peak_set = set(peaks.tolist())
    for i in range(frames):
        if i in peak_set:
            current = rng.random() * 100.0
        seed[i] = current

    move = np.cumsum(np.full(frames, 1.0 / fps) * (3.0 + low * 3.5))

    return Features(
        fps=fps, duration=duration, frames=frames,
        low=low, mid=mid, high=high, beat=beat, seed=seed, move=move,
        energy=energy, pulse=pulse, strike_times=strike_times,
    )
