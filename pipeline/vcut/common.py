"""Shared helpers: project paths, json io, ffprobe, time formatting."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECTS = ROOT / "projects"
VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".m4v", ".webm")
AUDIO_EXTS = (".wav", ".aif", ".aiff", ".m4a", ".mp3", ".flac")


@dataclass
class Project:
    name: str

    @property
    def dir(self) -> Path:
        return PROJECTS / self.name

    @property
    def inputs(self) -> Path:
        return self.dir / "inputs"

    @property
    def work(self) -> Path:
        p = self.dir / "work"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def out(self) -> Path:
        p = self.dir / "out"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def find_input(self, stem: str) -> Path:
        for ext in VIDEO_EXTS + AUDIO_EXTS:
            for cand in (self.inputs / f"{stem}{ext}", self.inputs / f"{stem}{ext.upper()}"):
                if cand.exists():
                    return cand
        raise SystemExit(
            f"Missing input: put the file at {self.inputs}/{stem}.mp4 (or .mov/.mkv). "
            f"Expected 'talking' (talking head) and 'screen' (screen recording)."
        )

    @property
    def talking(self) -> Path:
        return self.find_input("talking")

    @property
    def screen(self) -> Path:
        return self.find_input("screen")

    @property
    def audio(self) -> Path:
        return self.find_input("audio")

    def has_input(self, stem: str) -> bool:
        try:
            self.find_input(stem)
            return True
        except SystemExit:
            return False

    def originals(self) -> list[Path]:
        """Resolved paths of the input files (the user's originals behind the symlinks)."""
        if not self.inputs.exists():
            return []
        return sorted(p.resolve() for p in self.inputs.iterdir() if not p.name.startswith("."))


# ---------------------------------------------------------------- never touch the originals
# The inputs are your original recordings. Everything vcut writes must land inside projects/,
# and never on an original. Every write goes through ensure_writable(); every CLI command
# snapshots the originals' size+mtime before running and verifies them afterwards.

def ensure_writable(path: Path) -> Path:
    real = Path(path).resolve()
    root = PROJECTS.resolve()
    if root not in real.parents:
        raise SystemExit(f"Refusing to write outside {root}: {real}")
    if "inputs" in real.relative_to(root).parts[1:2]:
        raise SystemExit(f"Refusing to write into an inputs folder: {real}")
    for proj in PROJECTS.iterdir() if PROJECTS.exists() else []:
        if proj.is_dir() and real in Project(proj.name).originals():
            raise SystemExit(f"Refusing to overwrite an original recording: {real}")
    return Path(path)


def snapshot(paths: list[Path]) -> dict[str, tuple[int, int]]:
    return {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in paths if p.exists()}


def load_json(path: Path):
    return json.loads(Path(path).read_text())


def save_json(path: Path, data) -> None:
    ensure_writable(path)
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False))


def run(cmd: list[str], quiet: bool = True) -> str:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(map(str, cmd))}\n{res.stderr[-4000:]}")
    return res.stdout


def ffprobe(path: Path) -> dict:
    out = run([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ])
    return json.loads(out)


def parse_rate(s: str) -> Fraction:
    num, _, den = s.partition("/")
    return Fraction(int(num), int(den or 1)) if int(den or 1) else Fraction(0)


def fmt_time(t: float) -> str:
    """Seconds -> MM:SS.s (or H:MM:SS.s)."""
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{int(h)}:{int(m):02d}:{s:04.1f}"
    return f"{int(m):02d}:{s:04.1f}"


def norm_token(w: str) -> str:
    return "".join(ch for ch in w.lower() if ch.isalnum() or ch == "'").strip("'")
