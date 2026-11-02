"""Stage 1: inspect inputs, find how they line up, extract the master audio.

Inputs (projects/<name>/inputs/, symlinks to the read-only originals):
  talking.*  talking-head camera            (required)
  screen.*   screen recording                (required)
  audio.*    separate good-mic recording     (optional; becomes the master audio when present)

Sync: every source is placed on the master-audio clock. A source with sound is synced automatically
by cross-correlating it with the master audio. A source without sound needs its start time in
projects/<name>/sync.json, e.g. {"screen_start": 24.58} = "the screen recording's 00:00 happens
24.58 s into the master audio" (found from a cue such as saying "open / close" while toggling a tab).

All later stages work on the shared window where every source has content; `seek` in probe.json
is where that window starts inside each source file.
"""
from __future__ import annotations

from fractions import Fraction

import numpy as np
from scipy.signal import fftconvolve

from . import audio
from .common import Project, ffprobe, load_json, parse_rate, save_json

STANDARD_RATES = [Fraction(24000, 1001), Fraction(24), Fraction(25), Fraction(30000, 1001), Fraction(30),
                  Fraction(50), Fraction(60000, 1001), Fraction(60)]


def describe(path) -> dict:
    info = ffprobe(path)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    d = {"path": str(path), "duration": float(info["format"]["duration"]), "video": None, "audio": None}
    if v is not None:
        r = parse_rate(v.get("r_frame_rate", "0/1"))
        avg = parse_rate(v.get("avg_frame_rate", "0/1"))
        rotation = 0
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rotation = int(sd["rotation"])
        d.update({
            "video": True,
            "width": v["width"], "height": v["height"], "rotation": rotation, "codec": v["codec_name"],
            "r_frame_rate": str(r), "avg_frame_rate": str(avg),
            "vfr": bool(avg) and abs(float(r) - float(avg)) / float(avg) > 0.01,
            "video_start": float(v.get("start_time", 0) or 0),
        })
    if a is not None:
        d["audio"] = {"codec": a["codec_name"], "sample_rate": int(a["sample_rate"]),
                      "channels": a.get("channels", 1), "start": float(a.get("start_time", 0) or 0)}
    return d


def snap_rate(rate: Fraction) -> Fraction:
    best = min(STANDARD_RATES, key=lambda s: abs(float(s) - float(rate)))
    return best if abs(float(best) - float(rate)) < 0.05 else rate.limit_denominator(1001)


def _env100(x: np.ndarray, sr: int) -> np.ndarray:
    hop = sr // 100
    n = len(x) // hop
    e = np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(1))
    e = np.log(e + 1e-5)
    return e - e.mean()


def find_offset(master: np.ndarray, other: np.ndarray, sr: int) -> dict:
    """Where `other` starts on the master clock: master[t] == other[t - start].
    Coarse (10 ms) on loudness envelopes over the whole file, then sample-level at several windows."""
    em, eo = _env100(master, sr), _env100(other, sr)
    c = fftconvolve(em, eo[::-1], mode="full")
    k = int(np.argmax(c)) - (len(eo) - 1)
    strength = float(c.max() / (np.linalg.norm(em) * np.linalg.norm(eo) + 1e-9))
    start = k / 100.0
    fine = []
    usable = min(len(master) / sr, len(other) / sr + start)
    for at in np.linspace(max(30.0, start + 30), usable - 60, 8):
        w = 20 * sr
        a = int(at * sr)
        b = int((at - start) * sr)
        if b - sr < 0 or a + w > len(master) or b + w + sr > len(other):
            continue
        x, y = master[a:a + w], other[b - sr:b + w + sr]
        cc = fftconvolve(y, x[::-1], mode="valid")
        j = int(np.argmax(np.abs(cc)))
        s = float(np.abs(cc[j]) / (np.linalg.norm(x) * np.linalg.norm(y[j:j + w]) + 1e-9))
        fine.append({"at": round(at, 1), "start": round(start - (j - sr) / sr, 4), "strength": round(s, 3)})
    good = [f for f in fine if f["strength"] >= 0.15]
    if good:
        starts = np.array([f["start"] for f in good])
        ats = np.array([f["at"] for f in good])
        start = float(np.median(starts))
        drift_ms = float((np.polyfit(ats, starts, 1)[0] * (ats.max() - ats.min())) * 1000) if len(good) > 2 else 0.0
    else:
        drift_ms = 0.0
    return {"start": round(start, 4), "coarse_strength": round(strength, 3), "windows": fine,
            "drift_ms_over_file": round(drift_ms, 1), "confirmed": bool(good)}


def probe(project: Project, fps: str | None = None, until: float | None = None) -> dict:
    srcs = {"talking": describe(project.talking), "screen": describe(project.screen)}
    has_mic = project.has_input("audio")
    if has_mic:
        srcs["audio"] = describe(project.audio)
    master_name = "audio" if has_mic else "talking"
    if srcs[master_name]["audio"] is None:
        raise SystemExit(f"The {master_name} file has no audio track, but it is the master audio.")
    warnings: list[str] = []
    manual = load_json(project.dir / "sync.json") if (project.dir / "sync.json").exists() else {}

    talking = srcs["talking"]
    out_fps = Fraction(fps) if fps else snap_rate(
        parse_rate(talking["avg_frame_rate"] if talking["vfr"] else talking["r_frame_rate"]))
    for name in ("talking", "screen"):
        if srcs[name]["vfr"]:
            warnings.append(f"{name} is variable frame rate ({srcs[name]['avg_frame_rate']} avg). Converted to CFR on render.")

    # Master audio at 16k for sync + ASR (whole file, from the master's own 00:00)
    master_path = project.audio if has_mic else project.talking
    m_pad = 0.0 if has_mic else srcs["talking"]["audio"]["start"] - srcs["talking"]["video_start"]
    audio.extract(master_path, project.work / "master_full16k.wav", 16000, mono=True, start_pad=m_pad)
    master16, sr = audio.load_mono(project.work / "master_full16k.wav")

    # Start of every source on the master clock
    starts = {master_name: 0.0}
    sync_info = {}
    for name in ("talking", "screen"):
        if name == master_name:
            continue
        key = f"{name}_start"
        if key in manual:
            starts[name] = float(manual[key])
            sync_info[name] = {"start": starts[name], "source": "sync.json"}
            continue
        if srcs[name]["audio"] is None:
            raise SystemExit(
                f"The {name} file has no sound, so it can't be synced automatically. Find a cue (a clap, or "
                f"saying 'open/close' while toggling a tab) and write its start on the master clock to "
                f"{project.dir / 'sync.json'}, e.g. {{\"{key}\": 24.58}}.")
        tmp = project.work / f"{name}_full16k.wav"
        pad = srcs[name]["audio"]["start"] - srcs[name]["video_start"]
        audio.extract(getattr(project, name), tmp, 16000, mono=True, start_pad=pad)
        other, _ = audio.load_mono(tmp)
        res = find_offset(master16, other, sr)
        tmp.unlink(missing_ok=True)
        starts[name] = res["start"]
        sync_info[name] = {**res, "source": "audio"}
        if not res["confirmed"]:
            warnings.append(f"{name}: audio sync is weak (strength {res['coarse_strength']}). Check sync_check.mp4.")
        if abs(res["drift_ms_over_file"]) > 0.5 * 1000 / float(out_fps):
            warnings.append(f"{name}: clocks drift {res['drift_ms_over_file']} ms over the file (> half a frame).")

    # Shared window on the master clock where the camera and the master audio both have content. The screen
    # may start late or end early (e.g. a talking-head intro recorded before the screen recording started):
    # it is padded with black there, so seek["screen"] can be negative.
    core = [n for n in starts if n != "screen"]
    t0 = max(starts[n] for n in core)
    t1 = min(starts[n] + srcs[n]["duration"] for n in core)
    duration = t1 - t0
    if until:
        duration = min(duration, until)
    seek = {n: round(t0 - starts[n], 4) for n in starts}
    s0 = max(starts["screen"] - t0, 0.0)
    s1 = min(starts["screen"] + srcs["screen"]["duration"] - t0, duration)
    screen_covers = [round(s0, 4), round(s1, 4)]
    if s0 > 0 or s1 < duration:
        warnings.append(f"screen covers only {s0:.1f}s → {s1:.1f}s of the {duration:.1f}s window; black outside "
                        f"(use the full-screen talking head there).")

    # Master audio for the shared window: 48k (keep channels) for the mix, 16k mono for ASR/envelope
    audio.extract(master_path, project.work / "master.wav", 48000, mono=False, start_pad=m_pad,
                  seek=t0, duration=duration)
    m = master16[int(t0 * sr): int((t0 + duration) * sr)]
    import soundfile as sf
    sf.write(str(project.work / "asr16k.wav"), m, sr, subtype="FLOAT")
    (project.work / "master_full16k.wav").unlink(missing_ok=True)

    result = {
        **{n: srcs[n] for n in srcs},
        "master": master_name,
        "starts_on_master": starts,
        "window": [round(t0, 4), round(t0 + duration, 4)],
        "seek": seek,
        "screen_covers": screen_covers,
        "sync": sync_info,
        "fps": str(out_fps),
        "fps_float": float(out_fps),
        "duration": duration,
        "warnings": warnings,
    }
    save_json(project.work / "probe.json", result)
    return result
