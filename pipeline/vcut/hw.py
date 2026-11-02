"""This computer's hardware: which video encoder and decoder ffmpeg uses, and where the speech models run.

`vcut setup` detects it once and writes hardware.json at the repo root (git-ignored). It test-encodes a few frames
with each hardware encoder ffmpeg has (a listed encoder isn't proof: Windows builds list NVENC on machines with no
Nvidia card) and loads a tiny Whisper model on the GPU to see if it really works. Without the file, it's detected on
first use (encoders tested, speech models on the CPU).

  Apple Silicon Mac   VideoToolbox encode/decode, alignment on the GPU (MPS), recovery pass on the GPU (mlx-whisper)
  Nvidia GPU          NVENC encode, CUDA decode, Whisper on the GPU when CUDA works for it
  Intel / AMD GPU     QuickSync / AMF encode
  anything else       x264 on the CPU (slower, same result)

The 4K final (pipeline/tools/hybrid_render.py) uses VideoToolbox on a Mac and x264 everywhere else: its colours must
match Remotion's frames exactly, and x264 is the encoder Remotion itself uses.
"""
from __future__ import annotations

import ctypes
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .common import ROOT

CONFIG = ROOT / "hardware.json"

H264 = {"videotoolbox": "h264_videotoolbox", "nvenc": "h264_nvenc", "qsv": "h264_qsv", "amf": "h264_amf"}
HEVC = {"videotoolbox": "hevc_videotoolbox", "nvenc": "hevc_nvenc", "qsv": "hevc_qsv", "amf": "hevc_amf"}
DECODE = {"videotoolbox": "videotoolbox", "nvenc": "cuda", "qsv": "qsv"}  # AMF: software decode
EXTRA = {"nvenc": ["-preset", "p5"]}
X264_PRESET = "fast"
X264_CRF = {"master": "16", "proxy": "23"}

_profile: dict | None = None


def _ffmpeg(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", *args], capture_output=True, text=True)


def _encoders() -> str:
    return _ffmpeg(["-encoders"]).stdout


def _encodes(enc: str) -> bool:
    """A real 1440p test encode: the only proof the encoder works on this machine."""
    r = _ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=2560x1440:rate=25", "-frames:v", "10",
                 *encoder_args("8M", enc=enc), "-f", "null", "-"])
    return r.returncode == 0


def _decodes(hwaccel: str) -> bool:
    with tempfile.TemporaryDirectory() as td:
        clip = Path(td) / "t.mp4"
        r = _ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25", "-frames:v", "10", "-c:v", "libx264",
                     "-pix_fmt", "yuv420p", str(clip)])
        if r.returncode:
            return False
        return _ffmpeg(["-hwaccel", hwaccel, "-i", str(clip), "-f", "null", "-"]).returncode == 0


def _memory_gb() -> float:
    try:
        if os.name == "nt":
            class MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MemStatus(); m.dwLength = ctypes.sizeof(MemStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ullTotalPhys / 1e9
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
    except Exception:
        return 16.0


def _torch_device() -> str:
    try:
        import torch
        if torch.backends.mps.is_available():
            return "mps"
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _whisper_on_cuda() -> tuple[bool, str]:
    """Whisper (CTranslate2) and its voice detector (torch) both need CUDA: load the tiny model there and run it."""
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() == 0:
            return False, "no CUDA device"
        import numpy as np
        import whisperx
        m = whisperx.load_model("tiny", "cuda", compute_type="float16", language="en")
        m.transcribe(np.random.default_rng(0).normal(0, 0.01, 32000).astype(np.float32), batch_size=1)
        return True, "ok"
    except Exception as e:  # missing cuBLAS/cuDNN, CPU-only torch, …
        return False, f"{type(e).__name__}: {str(e)[:160]}"


def _can_symlink() -> bool:
    with tempfile.TemporaryDirectory(dir=ROOT) as td:
        try:
            os.symlink(Path(td) / "a", Path(td) / "b")
            return True
        except OSError:
            return False


def detect(full: bool = True) -> dict:
    """full: also try Whisper on the GPU (downloads the tiny model once). Encoders are always tested."""
    system, machine = platform.system().lower(), platform.machine().lower()
    notes = []
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg isn't installed (or isn't on the PATH): install it first.")
    listed = _encoders()
    if "libx264" not in listed:
        notes.append("this ffmpeg has no libx264: install a full ffmpeg build (the 4K final needs it)")
    order = ["videotoolbox"] if system == "darwin" else ["nvenc", "qsv", "amf"]
    encoder = next((e for e in order if H264[e] in listed and _encodes(e)), "x264")
    hwaccel = DECODE.get(encoder)
    if hwaccel and not _decodes(hwaccel):
        hwaccel = None

    torch_dev = _torch_device()
    asr = {"device": "cpu", "compute_type": "int8"}
    if full and torch_dev == "cuda":
        ok, why = _whisper_on_cuda()
        if ok:
            asr = {"device": "cuda", "compute_type": "float16"}
        else:
            notes.append(f"Nvidia GPU found, but Whisper can't use it ({why}); transcription runs on the CPU")
    mlx = system == "darwin" and machine == "arm64" and importlib.util.find_spec("mlx_whisper") is not None

    cores, mem = os.cpu_count() or 4, _memory_gb()
    tabs = max(2, min(10, cores - 2, int(mem / 2.4)))  # Remotion: each tab decodes video and holds frames
    if system == "windows" and not _can_symlink():
        notes.append("Windows can't make symlinks for this user: turn on Developer Mode (Settings → System → For "
                      "developers), so recordings can be linked instead of copied")
    return {
        "os": system, "machine": machine, "cpu_threads": cores, "memory_gb": round(mem, 1),
        "video": {"encoder": encoder, "hwaccel": hwaccel},
        "asr": asr,
        "align_device": torch_dev,
        "recovery": "mlx" if mlx else "whisper",
        "remotion": {"concurrency": tabs, "draft_concurrency": min(6, tabs)},
        "notes": notes,
    }


def setup() -> dict:
    """`vcut setup`: detect, write hardware.json, print what this computer will use."""
    print("[setup] testing the video encoders and the GPU (a minute or two the first time)…", flush=True)
    p = detect(full=True)
    CONFIG.write_text(json.dumps(p, indent=2) + "\n")
    global _profile
    _profile = p
    print(describe(p))
    print(f"[setup] saved {CONFIG}")
    return p


def describe(p: dict) -> str:
    enc = {"videotoolbox": "Apple VideoToolbox (GPU)", "nvenc": "Nvidia NVENC (GPU)", "qsv": "Intel QuickSync (GPU)",
           "amf": "AMD AMF (GPU)", "x264": "x264 (CPU, slower)"}[p["video"]["encoder"]]
    asr = "GPU (CUDA)" if p["asr"]["device"] == "cuda" else "CPU (int8)"
    rec = "GPU (mlx-whisper)" if p["recovery"] == "mlx" else f"same as transcription ({asr})"
    lines = [f"  computer:       {p['os']} {p['machine']}, {p['cpu_threads']} threads, {p['memory_gb']:.0f} GB",
             f"  video encode:   {enc}",
             f"  video decode:   {p['video']['hwaccel'] or 'CPU'}",
             f"  transcription:  {asr}",
             f"  word timing:    {p['align_device'].upper()}",
             f"  recovery pass:  {rec}",
             f"  4K final:       {'VideoToolbox' if p['video']['encoder'] == 'videotoolbox' else 'x264 (CPU)'}, "
             f"Remotion {p['remotion']['concurrency']} tabs (drafts {p['remotion']['draft_concurrency']})"]
    lines += [f"  ⚠️  {n}" for n in p.get("notes", [])]
    return "\n".join(lines)


def profile() -> dict:
    global _profile
    if _profile is None:
        if CONFIG.exists():
            _profile = json.loads(CONFIG.read_text())
        else:
            print("[hw] no hardware.json yet (run `vcut setup`): detecting the video encoder…", file=sys.stderr)
            _profile = detect(full=False)
    return _profile


# ------------------------------------------------------------------------------------------------- video

def encoder_args(bitrate: str | int, w: int = 0, h: int = 0, hevc: bool = False, enc: str | None = None,
                 quality: str = "master") -> list[str]:
    """ffmpeg video encoder arguments for this machine. Hardware encoders take the bitrate; x264 a quality level
    (quality="proxy" for the 720p draft proxies). H.264 hardware encoders stop at 4096 px, so wider goes HEVC."""
    enc = enc or profile()["video"]["encoder"]
    hevc = hevc or max(w, h) > 4096
    if enc == "x264":
        if hevc:
            return ["-c:v", "libx265", "-preset", X264_PRESET, "-crf", "18", "-tag:v", "hvc1"]
        return ["-c:v", "libx264", "-preset", X264_PRESET, "-crf", X264_CRF[quality], "-pix_fmt", "yuv420p"]
    if hevc:
        return ["-c:v", HEVC[enc], *EXTRA.get(enc, []), "-b:v", str(bitrate), "-tag:v", "hvc1"]
    return ["-c:v", H264[enc], *EXTRA.get(enc, []), "-b:v", str(bitrate), "-profile:v", "high"]


def decode_args() -> list[str]:
    """`-hwaccel …` before an input, or nothing (frames still come back to normal memory for the filters)."""
    acc = profile()["video"].get("hwaccel")
    return ["-hwaccel", acc] if acc else []


def final_encoder_args(bitrate: str) -> list[str]:
    """The 4K final / draft (hybrid_render.py): full-range BT.601 like Remotion's own frames. VideoToolbox on a Mac,
    x264 elsewhere (the encoder Remotion uses, and one that takes full-range YUV as is)."""
    if profile()["video"]["encoder"] == "videotoolbox":
        enc = ["-c:v", "h264_videotoolbox", "-b:v", bitrate, "-profile:v", "high"]
    else:
        enc = ["-c:v", "libx264", "-preset", X264_PRESET, "-b:v", bitrate, "-maxrate", bitrate,
               "-bufsize", bitrate, "-profile:v", "high"]
    return [*enc, "-pix_fmt", "yuvj420p", "-color_range", "pc", "-colorspace", "smpte170m", "-g", "250", "-an"]


def remotion_concurrency(draft: bool = False) -> int:
    r = profile()["remotion"]
    return r["draft_concurrency" if draft else "concurrency"]


# ------------------------------------------------------------------------------------------------- speech

def asr_device() -> tuple[str, str]:
    a = profile()["asr"]
    return a["device"], a["compute_type"]


def align_device() -> str:
    return profile().get("align_device", "cpu")


def use_mlx() -> bool:
    return profile().get("recovery") == "mlx" and importlib.util.find_spec("mlx_whisper") is not None


def whisper_model(name: str = "large-v3"):
    """faster-whisper model on this machine's ASR device (CPU int8 or CUDA float16)."""
    from faster_whisper import WhisperModel
    dev, ct = asr_device()
    if dev == "cpu":
        return WhisperModel(name, device="cpu", compute_type=ct, cpu_threads=max(4, (os.cpu_count() or 8) - 2))
    return WhisperModel(name, device=dev, compute_type=ct)


# ------------------------------------------------------------------------------------------------- misc

def keep_awake() -> None:
    """Keep the computer from sleeping while this process runs (long transcriptions and renders)."""
    try:
        if sys.platform == "darwin" and shutil.which("caffeinate"):
            subprocess.Popen(["caffeinate", "-is", "-w", str(os.getpid())])
        elif os.name == "nt":
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)  # CONTINUOUS | SYSTEM_REQUIRED
        elif shutil.which("systemd-inhibit"):
            subprocess.Popen(["systemd-inhibit", "--what=sleep:idle", "--why=video render", "--mode=block",
                              "tail", f"--pid={os.getpid()}", "-f", "/dev/null"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def npx() -> str:
    """npx's real path (npx.cmd on Windows, which subprocess won't find by the bare name)."""
    return shutil.which("npx") or "npx"


def kill_headless_chrome(root: Path) -> None:
    """Remotion's headless Chrome sometimes outlives a crashed render: end it before the retry."""
    marker = str(root / "remotion/node_modules/.remotion/chrome-headless-shell")
    if shutil.which("pkill"):
        subprocess.run(["pkill", "-f", marker])
    elif os.name == "nt":
        subprocess.run(["taskkill", "/F", "/IM", "chrome-headless-shell.exe"], capture_output=True)


def main() -> None:
    """python -m vcut.hw [key.path]: print the profile, or one value (for the shell scripts)."""
    p = profile()
    if len(sys.argv) > 1:
        v = p
        for k in sys.argv[1].split("."):
            v = v[k]
        print(v)
    else:
        print(describe(p))


if __name__ == "__main__":
    main()
