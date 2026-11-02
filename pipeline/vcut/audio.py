"""Audio extraction, loudness envelope, silence runs and sync cross-correlation."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import fftconvolve

from .common import ensure_writable, run

ENV_HOP = 0.005  # envelope resolution: 5 ms
ENV_WIN = 0.010  # 10 ms RMS window


def extract(src: Path, dst: Path, sr: int, mono: bool, start_pad: float = 0.0,
            seek: float | None = None, duration: float | None = None) -> None:
    """Extract first audio stream to float wav (reads src only). start_pad>0 prepends silence
    (audio starting late); seek/duration then cut a window out of the padded stream."""
    ensure_writable(dst)
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-map", "0:a:0", "-vn"]
    if mono:
        cmd += ["-ac", "1"]
    af = []
    if start_pad > 0:
        ms = int(round(start_pad * 1000))
        af.append(f"adelay={ms}:all=1")
    elif start_pad < 0:
        af.append(f"atrim=start={-start_pad},asetpts=PTS-STARTPTS")
    if seek is not None or duration is not None:
        trim = [f"start={seek or 0}"] + ([f"duration={duration}"] if duration else [])
        af.append(f"atrim={':'.join(trim)},asetpts=PTS-STARTPTS")
    if af:
        cmd += ["-af", ",".join(af)]
    # rf64 auto: a 48k stereo float master passes the 4 GB WAV limit at ~3.1 h; a plain RIFF header then overflows and
    # readers see only the first 3:06 (a 45-min cut went silent from 42:13 on)
    cmd += ["-ar", str(sr), "-c:a", "pcm_f32le", "-rf64", "auto", str(dst)]
    run(cmd)


def load(path: Path) -> tuple[np.ndarray, int]:
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    return data, sr


def load_mono(path: Path) -> tuple[np.ndarray, int]:
    data, sr = load(path)
    return data.mean(axis=1), sr


def envelope_db(mono: np.ndarray, sr: int) -> np.ndarray:
    """RMS loudness in dBFS, one value per ENV_HOP seconds (value i covers t = i*hop)."""
    hop = int(sr * ENV_HOP)
    win = int(sr * ENV_WIN)
    pad = np.concatenate([np.zeros(win // 2, np.float32), mono, np.zeros(win, np.float32)])
    n = len(mono) // hop + 1
    sq = np.cumsum(np.concatenate([[0.0], pad.astype(np.float64) ** 2]))
    idx = np.arange(n) * hop
    energy = (sq[idx + win] - sq[idx]) / win
    return (10 * np.log10(energy + 1e-12)).astype(np.float32)


class Envelope:
    """Loudness envelope with a speech threshold derived from the recording's own noise floor."""

    def __init__(self, db: np.ndarray, speech_margin_db: float = 10.0):
        self.db = db
        voiced = db[db > -90]
        self.floor = float(np.percentile(voiced, 8)) if len(voiced) else -80.0
        self.peak = float(np.percentile(voiced, 98)) if len(voiced) else -10.0
        # Threshold sits a margin above the floor, but never above ~40% of the dynamic range
        self.thr = min(self.floor + speech_margin_db, self.floor + 0.4 * (self.peak - self.floor))

    def i(self, t: float) -> int:
        return int(np.clip(round(t / ENV_HOP), 0, len(self.db) - 1))

    def t(self, i: int) -> float:
        return i * ENV_HOP

    def silent(self, t0: float, t1: float) -> np.ndarray:
        a, b = self.i(t0), self.i(t1)
        return self.db[a:b] < self.thr

    def longest_silence(self, t0: float, t1: float) -> tuple[float, float] | None:
        """Longest below-threshold run inside [t0, t1] as (start, end) seconds."""
        if t1 - t0 < ENV_HOP * 2:
            return None
        a = self.i(t0)
        mask = self.silent(t0, t1)
        best, cur_start = None, None
        for k, s in enumerate(np.append(mask, False)):
            if s and cur_start is None:
                cur_start = k
            elif not s and cur_start is not None:
                if best is None or (k - cur_start) > (best[1] - best[0]):
                    best = (cur_start, k)
                cur_start = None
        if best is None:
            return None
        return self.t(a + best[0]), self.t(a + best[1])

    def quietest(self, t0: float, t1: float) -> float:
        a, b = self.i(t0), max(self.i(t1), self.i(t0) + 1)
        return self.t(a + int(np.argmin(self.db[a:b])))

    def is_speech_at(self, t: float, radius: float = 0.012) -> bool:
        a, b = self.i(t - radius), self.i(t + radius) + 1
        return bool(np.any(self.db[a:b] >= self.thr))

    def speech_regions(self, min_len: float = 0.25, bridge: float = 0.12) -> list[tuple[float, float]]:
        """Regions above threshold, bridging short dips, dropping very short blips."""
        mask = self.db >= self.thr
        regions, start = [], None
        for k, s in enumerate(np.append(mask, False)):
            if s and start is None:
                start = k
            elif not s and start is not None:
                regions.append([self.t(start), self.t(k)])
                start = None
        merged: list[list[float]] = []
        for r in regions:
            if merged and r[0] - merged[-1][1] <= bridge:
                merged[-1][1] = r[1]
            else:
                merged.append(r)
        return [(a, b) for a, b in merged if b - a >= min_len]


def xcorr_offset(a: np.ndarray, b: np.ndarray, sr: int, max_lag: float = 2.0) -> tuple[float, float]:
    """Offset (seconds) of b relative to a, and normalised peak strength (0..1)."""
    n = min(len(a), len(b))
    a = a[:n] - a[:n].mean()
    b = b[:n] - b[:n].mean()
    if not np.any(a) or not np.any(b):
        return 0.0, 0.0
    corr = fftconvolve(b, a[::-1], mode="full")
    mid = n - 1
    lag_max = int(max_lag * sr)
    window = corr[mid - lag_max: mid + lag_max + 1]
    k = int(np.argmax(np.abs(window)))
    strength = float(np.abs(window[k]) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
    return (k - lag_max) / sr, strength


def sync_check(a: np.ndarray, b: np.ndarray, sr: int, win: float = 20.0, points: int = 5) -> list[dict]:
    """Cross-correlate a and b at several windows across the timeline."""
    n = min(len(a), len(b))
    w = int(win * sr)
    if n < w:
        starts = [0]
        w = n
    else:
        starts = np.linspace(0, n - w, points).astype(int).tolist()
    out = []
    for s in starts:
        off, strength = xcorr_offset(a[s:s + w], b[s:s + w], sr)
        out.append({"at": round(s / sr, 2), "offset_ms": round(off * 1000, 1), "strength": round(strength, 3)})
    return out
