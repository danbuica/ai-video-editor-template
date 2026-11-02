"""assets.py — your own music and sound effects (any free library works, e.g. the YouTube Audio Library).

  uv run --project pipeline python pipeline/tools/assets.py sfx
      Every sound in projects/_assets/sfx (wav/mp3/m4a/aiff/flac/ogg) → a .wav next to it (Remotion plays the .wav) and
      projects/_assets/sfx/library.json: length, the loudest moment (`peak_at`, so `"hit": true` lands it on the cue)
      and a loudness trim that evens out quiet and loud samples. Re-run after adding sounds.
  uv run --project pipeline python pipeline/tools/assets.py music <project> <track> [--skip-intro 8]
      A seamless music bed as long as the video (crossfaded repeats, fade-out) → projects/<project>/out/music_bed.wav,
      and prints the `music` entry for motion.json (with the bed's loudness, which Final.tsx normalises).
Tracks can live anywhere; keep your library in projects/_assets/music.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vcut.common import PROJECTS, load_json, save_json  # noqa: E402
from vcut.music import build_bed  # noqa: E402

SFX_DIR = PROJECTS / "_assets" / "sfx"
EXTS = (".wav", ".mp3", ".m4a", ".aif", ".aiff", ".flac", ".ogg")


def sfx() -> None:
    files = sorted(p for p in SFX_DIR.glob("*") if p.suffix.lower() in EXTS)
    if not files:
        raise SystemExit(f"No sounds in {SFX_DIR}. Put your sound effects there (one file per sound) and re-run.")
    for p in files:
        if p.suffix.lower() != ".wav" and not p.with_suffix(".wav").exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(p), "-ar", "48000", "-ac", "2", str(p.with_suffix(".wav"))], check=True)
    lib = {}
    for p in sorted(SFX_DIR.glob("*.wav")):
        x, sr = sf.read(str(p), dtype="float32", always_2d=True)
        mono = np.abs(x).max(axis=1)
        hop = int(0.005 * sr)
        env = np.array([mono[i:i + hop].max() for i in range(0, len(mono), hop)]) if len(mono) else np.zeros(1)
        peak_at = float(np.argmax(env) * 0.005)
        loud = x[np.abs(x).max(axis=1) > 10 ** (-40 / 20)]
        rms = float(np.sqrt(np.mean(loud ** 2))) if len(loud) else 1e-6
        lib[p.stem] = {"file": f"_assets/sfx/{p.name}", "duration": round(len(x) / sr, 3), "peak_at": round(peak_at, 3),
                       "level_db": round(20 * np.log10(rms + 1e-12), 1)}
    target = statistics.median(v["level_db"] for v in lib.values())
    for v in lib.values():
        v["trim_db"] = round(float(np.clip(target - v["level_db"], -9, 9)), 1)
    save_json(SFX_DIR / "library.json", lib)
    print(f"{len(lib)} sounds → {SFX_DIR / 'library.json'}")
    for name, v in lib.items():
        print(f"  {name:28s} {v['duration']:5.2f}s  peak at {v['peak_at']:.2f}s  trim {v['trim_db']:+.1f} dB")


def music(project: str, track: str, skip_intro: float) -> None:
    out = PROJECTS / project / "out"
    edl = load_json(out / "edl.json")
    duration = edl["out_frames"] / edl["fps_float"] + 30  # + room for chapter cards; Final fades the music at the end
    dst = out / "music_bed.wav"
    lufs = build_bed(Path(track), dst, duration, skip_intro=skip_intro)
    entry = {"file": f"{project}/out/music_bed.wav", "lufs": round(lufs, 1), "gainDb": 0, "label": Path(track).stem}
    print(f"bed {duration:.0f}s → {dst}\nmotion.json \"music\": {json.dumps(entry)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("sfx")
    m = sp.add_parser("music")
    m.add_argument("project")
    m.add_argument("track")
    m.add_argument("--skip-intro", type=float, default=0.0, help="later repeats skip this many seconds of the track's intro")
    a = ap.parse_args()
    sfx() if a.cmd == "sfx" else music(a.project, a.track, a.skip_intro)
