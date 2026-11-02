"""Build a synthetic project with known retakes, a mid-sentence pause and a backtrack.

talking.mp4: 30 fps testsrc (shows its frame number) + TTS narration (master mic, clips in tests/voice/)
screen.mp4 : 60 fps VFR testsrc (frame number = 2x talking's) + the same speech through a "worse mic"

Usage: uv run --project pipeline python pipeline/tests/make_synthetic.py [project_name]   (default: example)
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
SR = 48000
VOICE = Path(__file__).resolve().parent / "voice"

# (text, pause_after_seconds). Comments: what the cutter must do.
SCRIPT = [
    ("This is the map of every", 1.3),                                   # failed take → cut
    ("This is the map of every agent I use to run my business.", 0.9),   # keeper
    ("And the first one", 1.6),                                          # mid-sentence thinking pause → close gap
    ("is the research agent.", 0.8),
    ("It finds the best videos on", 1.1),                                # backtrack: "videos on" repeated → cut first copy
    ("videos on YouTube every single morning.", 1.0),
    ("Then the second agent writes the script.", 0.7),                   # retake → cut
    ("Wait, let me say that again.", 1.2),                               # marker → cut
    ("Then the second agent writes the full script for me.", 1.4),       # keeper; long sentence pause → shorten
    ("Um.", 0.7),                                                        # filler → cut
    ("And that is basically the whole system.", 1.5),
]
EXPECTED = ("This is the map of every agent I use to run my business. And the first one is the research agent. "
            "It finds the best videos on YouTube every single morning. Then the second agent writes the full "
            "script for me. And that is basically the whole system.")


def tts(text: str, tmp: Path, idx: int) -> np.ndarray:
    """Line idx of SCRIPT, spoken. The clips in tests/voice/ were made once with a text-to-speech voice and trimmed of
    their own leading/trailing silence (so our pauses are exact): the example builds the same on any computer."""
    data, sr = sf.read(str(VOICE / f"{idx:02d}.flac"), dtype="float32")
    assert sr == SR, f"{VOICE / f'{idx:02d}.flac'}: {sr} Hz, expected {SR}"
    return data


def main(name: str = "example") -> None:
    proj = ROOT / "projects" / name
    (proj / "inputs").mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        parts = [np.zeros(int(0.8 * SR), np.float32)]
        for i, (text, pause) in enumerate(SCRIPT):
            parts.append(tts(text, tmp, i))
            parts.append(np.zeros(int(pause * SR), np.float32))
        voice = np.concatenate(parts)
        dur = len(voice) / SR
        room = rng.normal(0, 10 ** (-58 / 20), len(voice)).astype(np.float32)        # room tone
        master = voice * 0.5 + room
        cheap = np.convolve(voice, np.ones(8) / 8, mode="same") * 0.3 \
            + rng.normal(0, 10 ** (-48 / 20), len(voice)).astype(np.float32)        # worse mic, noisier
        sf.write(str(tmp / "master.wav"), master, SR)
        sf.write(str(tmp / "screen.wav"), cheap, SR)

        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size=1280x720:rate=30:duration={dur}",
            "-i", str(tmp / "master.wav"), "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "256k", str(proj / "inputs" / "talking.mp4"),
        ], check=True)
        # 60 fps then drop every 7th frame and keep VFR timestamps → mimics a screen recorder
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size=1920x1080:rate=60:duration={dur}",
            "-i", str(tmp / "screen.wav"), "-vf", "select='not(eq(mod(n\\,7)\\,3))'", "-fps_mode", "vfr",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            str(proj / "inputs" / "screen.mp4"),
        ], check=True)
    (proj / "expected.txt").write_text(EXPECTED + "\n")
    print(f"Built {proj} ({dur:.1f}s)")


if __name__ == "__main__":
    main(*sys.argv[1:])
