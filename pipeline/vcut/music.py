"""Build a seamless music bed of a given length from one track: repeat it with long equal-power
crossfades (no hard loop restarts), fade out at the end, report its loudness."""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from .common import ensure_writable


def build_bed(track: Path, dst: Path, duration: float, xfade: float = 6.0, skip_intro: float = 0.0) -> float:
    ensure_writable(dst)
    x, sr = sf.read(str(track), dtype="float32", always_2d=True)
    n_total = int(duration * sr)
    xf = int(xfade * sr)
    out = x.copy()
    body = x[int(skip_intro * sr):]  # later repeats can skip the intro so the bed doesn't "restart"
    t = np.linspace(0, np.pi / 2, xf, dtype=np.float32)[:, None]
    fo, fi = np.cos(t), np.sin(t)
    while len(out) < n_total + xf:
        head = out[:-xf]
        mix = out[-xf:] * fo + body[:xf] * fi
        out = np.concatenate([head, mix, body[xf:]])
    out = out[:n_total]
    fade = int(4.0 * sr)
    out[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)[:, None]
    sf.write(str(dst), out, sr, subtype="PCM_16")
    res = subprocess.run(["ffmpeg", "-nostats", "-i", str(dst), "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
                         capture_output=True, text=True)
    lufs = float([ln for ln in res.stderr.splitlines() if ln.strip().startswith("I:")][-1].split()[1])
    return lufs
