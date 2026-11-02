"""Stage 6: render both cut files from the same EDL.

Video: decode → force CFR on the shared frame grid → keep frames by index → encode (this machine's
encoder, vcut/hw.py).
Audio: cut sample-accurately in numpy on the same frame boundaries, with short equal-power
fades at every join (no length change), then muxed in.
"""
from __future__ import annotations

import time
from fractions import Fraction
from pathlib import Path

import numpy as np
import soundfile as sf

from . import audio, hw
from .common import Project, ensure_writable, load_json, run

FADE = 0.004  # 4 ms fade out / fade in at each join


def cut_audio(src_wav: Path, dst_wav: Path, edl: dict) -> None:
    ensure_writable(dst_wav)
    data, sr = audio.load(src_wav)
    fps = Fraction(edl["fps"])
    n_src = len(data)

    def samp(frame: int) -> int:
        return int(round(frame / fps * sr))

    total = samp(edl["out_frames"])
    out = np.zeros((total, data.shape[1]), np.float32)

    def src_slice(a: int, b: int) -> np.ndarray:
        """Source samples [a, b), zero-padded outside the file."""
        res = np.zeros((b - a, data.shape[1]), np.float32)
        lo, hi = max(a, 0), min(b, n_src)
        if hi > lo:
            res[lo - a: hi - a] = data[lo:hi]
        return res

    bounds = []
    for sg in edl["segments"]:
        o = samp(sg["out_start"])
        n = samp(sg["out_start"] + sg["src_end"] - sg["src_start"]) - o
        # audio_offset_s: the segment's audio may sit up to half a frame off the video edge so
        # tight cuts land on their quietest millisecond; length always equals the video's.
        a = samp(sg["src_start"]) + int(round(sg.get("audio_offset_s", 0.0) * sr))
        n = min(n, total - o)
        out[o:o + n] = src_slice(a, a + n)
        bounds.append((o, o + n))

    # Short raised-cosine fade out/in at every join. Nothing from the removed audio bleeds in,
    # which matters for tight cuts; at joins in silence the dip is inaudible.
    h = int(FADE * sr)
    ramp = (0.5 - 0.5 * np.cos(np.linspace(0, np.pi, h, dtype=np.float32)))[:, None]
    for (s1, e1), (s2, e2) in zip(bounds, bounds[1:]):
        if e1 - s1 > 2 * h:
            out[e1 - h:e1] *= ramp[::-1]
        if e2 - s2 > 2 * h:
            out[s2:s2 + h] *= ramp

    # 10 ms fade at the very start and end
    e = min(int(0.01 * sr), total // 2)
    if e:
        ramp = np.linspace(0, 1, e, dtype=np.float32)[:, None]
        out[:e] *= ramp
        out[-e:] *= ramp[::-1]
    sf.write(str(dst_wav), out, sr, subtype="FLOAT")


def _bitrate(w: int, h: int, fps: float) -> int:
    return int(min(150e6, max(8e6, w * h * fps * 0.25)))


def _venc(encoder: str, w: int, h: int, fpsf: float) -> list[str]:
    """auto = this machine's encoder (hardware.json: VideoToolbox, NVENC, QuickSync, AMF or x264)."""
    return hw.encoder_args(_bitrate(w, h, fpsf), w, h, hevc=encoder == "hevc", enc="x264" if encoder == "x264" else None)


def _out_size(info: dict, max_height: int | None) -> tuple[int, int, str]:
    w, h = info["width"], info["height"]
    if abs(info.get("rotation", 0)) in (90, 270):
        w, h = h, w
    if max_height and h > max_height:  # e.g. 4K camera → 1440p: plenty for a 1080p edit, much faster in Remotion
        w, h = int(round(w * max_height / h / 2)) * 2, max_height
        return w, h, f"scale={w}:{h}:flags=lanczos,"
    return w, h, ""


def cfr_copy(src: Path, dst: Path, fps: str, seek: float, duration: float, info: dict) -> Path:
    """Variable-frame-rate sources (screen recordings) → one constant-frame-rate working copy of the
    shared window, so every later seek lands on an exact frame. Same frame mapping as a full pass:
    output frame n = the source frame showing at n/fps."""
    ensure_writable(dst)
    stamp = dst.with_suffix(".json")
    key = f"{src.resolve()}|{fps}|{seek:.4f}|{duration:.4f}"
    if dst.exists() and stamp.exists() and stamp.read_text() == key:
        return dst
    w, h, _ = _out_size(info, None)
    # A source that starts after the window (negative seek) or ends before it is padded: black before,
    # last frame held after. -t on the output keeps the frame count exact.
    pad = (f",tpad=start_duration={-seek:.4f}:color=black" if seek < 0 else "") + ",tpad=stop_mode=clone:stop=-1"
    run([
        "ffmpeg", "-y", "-v", "error", *hw.decode_args(),
        *(["-ss", f"{seek:.4f}"] if seek > 0 else []), "-i", str(src), "-an",
        "-vf", f"setpts=PTS-STARTPTS,fps={fps}:round=near{pad},format=yuv420p", "-t", f"{duration:.4f}",
        *_venc("auto", w, h, float(Fraction(fps))), "-g", str(int(round(float(Fraction(fps)) * 2))),
        "-r", fps, str(dst),
    ])
    ensure_writable(stamp).write_text(key)
    return dst


def _chunks(segments: list[dict], max_gap: int = 250, max_segs: int = 40) -> list[list[dict]]:
    groups: list[list[dict]] = []
    for sg in segments:
        prev = groups[-1][-1] if groups else None
        if (prev is not None and not sg.get("hold") and not prev.get("hold")
                and 0 <= sg["src_start"] - prev["src_end"] <= max_gap and len(groups[-1]) < max_segs):
            groups[-1].append(sg)
        else:
            groups.append([sg])
    return groups


def screen_resync(edl: dict, anchors: list[list[float]], fps: float,
                  out_overrides: list[list] | None = None) -> list[dict]:
    """Re-time the screen against the voice. anchors = [[voice_t, screen_t], ...] (window seconds, increasing).
    Before the first anchor the screen is in sync (screen_t = voice_t). After an anchor it plays in real time
    from that anchor's screen_t, but holds just before the next anchor's screen_t until its voice_t arrives
    (the screen recording lost time during static stretches, so slides must wait for the sentence).
    out_overrides = [[out_from_s, out_to_s, screen_t, ("hold")], ...]: on the FINAL timeline, play the screen
    continuously from screen_t (or hold that frame), ignoring cuts in the voice (e.g. a click-through demo)."""
    import bisect
    vts = [a[0] for a in anchors]

    def warp(t: float) -> float:
        i = bisect.bisect_right(vts, t) - 1
        if i < 0:
            return t
        st = anchors[i][1] + (t - anchors[i][0])
        if i + 1 < len(anchors):
            st = min(st, anchors[i + 1][1] - 1.0 / fps)
        return st

    frames: list[int] = []
    for sg in edl["segments"]:
        for f in range(sg["src_start"], sg["src_end"]):
            frames.append(int(round(warp(f / fps) * fps)))
    for ov in out_overrides or []:
        o0, o1, st = int(round(ov[0] * fps)), int(round(ov[1] * fps)), ov[2]
        hold = len(ov) > 3 and ov[3] == "hold"
        for o in range(max(0, o0), min(len(frames), o1)):
            frames[o] = int(round(st * fps)) + (0 if hold else o - o0)

    runs: list[dict] = []
    for sf in frames:
        last = runs[-1] if runs else None
        if last and not last["hold"] and sf == last["src_end"]:
            last["src_end"] += 1
        elif last and sf == last["src_start"] and (last["hold"] or last["src_end"] - last["src_start"] == 1):
            last["hold"] = True
            last["n"] = last.get("n", 1) + 1
        else:
            runs.append({"src_start": sf, "src_end": sf + 1, "hold": False})
    for r in runs:
        if r["hold"]:
            r["src_end"] = r["src_start"] + 1
        r.setdefault("n", r["src_end"] - r["src_start"])
    return runs


def render_one(src: Path, wav: Path, dst: Path, edl: dict, info: dict, encoder: str, seek: float = 0.0,
               max_height: int | None = None, work: Path | None = None, name: str = "video",
               segments: list[dict] | None = None) -> None:
    """Render one cut file. Segments are grouped into chunks of nearby segments; each chunk seeks
    straight to its first frame (so cut-away material is never decoded), keeps frames by local index,
    and the chunks are concatenated losslessly. Audio is muxed in a final stream-copy pass."""
    from concurrent.futures import ThreadPoolExecutor

    ensure_writable(dst)
    fps = edl["fps"]
    fpsf = edl["fps_float"]
    w, h, scale = _out_size(info, max_height)
    venc = _venc(encoder, w, h, fpsf)
    cdir = (work or dst.parent) / f"chunks_{name}"
    cdir.mkdir(parents=True, exist_ok=True)
    for old in cdir.glob("*"):
        old.unlink()
    groups = _chunks(segments or edl["segments"])

    def one(idx_group):
        i, g = idx_group
        cs = g[0]["src_start"]
        if g[0].get("hold"):  # one source frame held for n output frames
            n = g[0]["n"]
            out = ensure_writable(cdir / f"{i:04d}.mp4")
            run([
                "ffmpeg", "-y", "-v", "error", *hw.decode_args(),
                "-ss", f"{max(seek + (cs - 0.3) / fpsf, 0):.4f}", "-i", str(src), "-an",
                "-vf", f"setpts=PTS-STARTPTS,fps={fps}:round=near,select='eq(n,0)',loop=loop={n - 1}:size=1:start=0,"
                       f"setpts=N/({fps})/TB,{scale}format=yuv420p",
                *venc, "-g", str(int(round(fpsf * 2))), "-r", fps, "-frames:v", str(n), str(out),
            ])
            return out
        n_frames = sum(sg["src_end"] - sg["src_start"] for sg in g)
        terms = "+".join(f"between(n,{sg['src_start'] - cs},{sg['src_end'] - 1 - cs})" for sg in g)
        out = ensure_writable(cdir / f"{i:04d}.mp4")
        # seek 0.3 frame before frame cs, so the first decoded frame is exactly frame cs
        t = seek + (cs - 0.3) / fpsf
        run([
            "ffmpeg", "-y", "-v", "error", *hw.decode_args(),
            "-ss", f"{max(t, 0):.4f}", "-i", str(src), "-an",
            "-vf", f"setpts=PTS-STARTPTS,fps={fps}:round=near,select='{terms}',setpts=N/({fps})/TB,{scale}format=yuv420p",
            *venc, "-g", str(int(round(fpsf * 2))), "-r", fps, "-frames:v", str(n_frames), str(out),
        ])
        return out

    with ThreadPoolExecutor(max_workers=3) as ex:
        parts = list(ex.map(one, enumerate(groups)))
    lst = ensure_writable(cdir / "list.txt")
    lst.write_text("".join(f"file '{p_.name}'\n" for p_ in parts))
    run([
        "ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(wav),
        "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "320k",
        "-movflags", "+faststart", str(dst),
    ])
    for old in cdir.glob("*"):
        old.unlink()
    cdir.rmdir()


def render(project: Project, encoder: str = "auto", only: str | None = None, talking_height: int | None = 1440) -> None:
    edl = load_json(project.out / "edl.json")
    probe = load_json(project.work / "probe.json")
    t0 = time.time()
    print(f"[render] cutting audio ({len(edl['segments'])} segments)…", flush=True)
    cut_audio(project.work / "master.wav", project.work / "cut_master.wav", edl)

    jobs = [("talking", project.talking, project.out / "talking_cut.mp4"),
            ("screen", project.screen, project.out / "screen_cut.mp4")]
    for name, src, dst in jobs:
        if only and name != only:
            continue
        info, seek = probe[name], probe.get("seek", {}).get(name, 0.0)
        if info.get("vfr") or seek < 0:
            print(f"[render] {name}: making a constant-frame-rate working copy (one time)…", flush=True)
            src = cfr_copy(src, project.work / f"{name}_cfr.mp4", edl["fps"], seek, probe["duration"], info)
            seek = 0.0
        segs = None
        sync_file = project.dir / "screen_sync.json"
        if name == "screen" and sync_file.exists():
            sync = load_json(sync_file)
            anchors = sync["anchors"]
            segs = screen_resync(edl, [[a[0], a[1]] for a in anchors], edl["fps_float"], sync.get("out_overrides"))
            assert sum(r["n"] for r in segs) == edl["out_frames"]
            print(f"[render] screen: re-synced with {len(anchors)} anchors "
                  f"({sum(1 for r in segs if r['hold'])} held stills)", flush=True)
        print(f"[render] {name} → {dst.name} ({edl['out_frames']} frames @ {edl['fps']}, "
              f"{len(_chunks(segs or edl['segments']))} chunks)…", flush=True)
        render_one(src, project.work / "cut_master.wav", dst, edl, info, encoder, seek=seek,
                   max_height=talking_height if name == "talking" else None, work=project.work, name=name,
                   segments=segs)
        print(f"[render]   done at {time.time() - t0:.0f}s", flush=True)
        make_proxy(project, name)
    print(f"[render] done in {time.time() - t0:.0f}s", flush=True)


PROXY_BITRATE = {"talking": "6M", "screen": "3M"}


def make_proxy(project: Project, name: str) -> Path:
    """720p copy of a cut file for fast Remotion drafts (props `"proxy": true`). Remotion decodes every source frame
    on the CPU, and at full resolution that was ~95% of draft render time; the proxy cuts it ~4x. Hardware
    decode/encode, a keyframe every second for cheap seeking, same frame count. Rebuilt whenever the cut is rendered."""
    src = project.out / f"{name}_cut.mp4"
    dst = project.out / "proxy" / f"{name}_cut.mp4"
    ensure_writable(dst)
    dst.parent.mkdir(exist_ok=True)
    t0 = time.time()
    audio_args = ["-c:a", "copy"] if name == "talking" else ["-an"]
    # keep the aspect (just large enough to cover 1280x720, like object-fit: cover): a plain 1280:720 squashed the
    # 2380x1404 screen 5% in drafts, while the 4K crops it
    fit = "scale=w='if(gt(a,16/9),-2,1280)':h='if(gt(a,16/9),720,-2)'"
    run(["ffmpeg", "-v", "error", "-y", *hw.decode_args(), "-i", str(src), "-vf", fit,
         *hw.encoder_args(PROXY_BITRATE[name], quality="proxy"), "-g", "25", *audio_args, str(dst)])
    print(f"[render] {name}: 720p draft proxy in {time.time() - t0:.0f}s", flush=True)
    return dst
