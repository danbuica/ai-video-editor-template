"""Final audio mastering: bring the finished mix to YouTube loudness (-14 LUFS integrated, -1 dBTP)
with a two-pass linear loudnorm. Video is stream-copied (no re-encode)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .common import ensure_writable


def measure(src: Path) -> dict:
    res = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-af", "loudnorm=I=-14:TP=-1.0:LRA=11:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    blob = res.stderr[res.stderr.rindex("{"): res.stderr.rindex("}") + 1]
    return json.loads(blob)


def master(src: Path, dst: Path, target: float = -14.0, tp: float = -1.0) -> dict:
    ensure_writable(dst)
    m = measure(src)
    af = (f"loudnorm=I={target}:TP={tp}:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-c:v", "copy", "-af", af, "-ar", "48000",
                    "-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart", str(dst)], check=True)
    return {"input_lufs": float(m["input_i"]), "target": target}
