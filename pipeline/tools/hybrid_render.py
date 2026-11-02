"""Fast 4K final (~3× faster than an all-Remotion render, same picture and sound): ffmpeg draws every plain frame
(screen + face card), Remotion only the rest (graphics, full-screen head, images, zooms, blurs, chapter cards).

  uv run --project pipeline --with "opencv-python-headless<4.12" python pipeline/tools/hybrid_render.py <name>
      [--motion motion.json] [--concurrency 10] [--out <name>_final_4k.mp4]
      [--draft]   720p draft from the out/proxy/ files instead → out/<name>_draft_720p.mp4 (work dir out/hybrid_draft/)

Re-run the same command after a crash: every step skips what is already done. A change to the cut, layout, motion file,
props or Remotion code (inputs.txt fingerprint) starts the frames and runs over.
  1. pipeline/tools/hybrid_plan.py → out/hybrid/plan.json (runs of plain / Remotion frames)
  2. Remotion `FinalSubset` (only the Remotion frames, back to back), in chunks of --chunk frames → out/hybrid/frames/NNNNNN.jpeg
  3. one ffmpeg encode per run → out/hybrid/run_NNN.mp4, all with the SAME encoder settings, so they join with -c copy:
       plain:    screen (object-fit cover) + card shadow + camera crop in a rounded card, drawn like Main.tsx
       remotion: the run's JPEG frames (the exact pictures Remotion's own encoder would get)
  4. concat → video.mp4; pipeline/tools/hybrid_audio.py → audio.wav (Final's mix in numpy, nulls Remotion at −64.7 dB);
     mux → joined.mov (PCM); vcut.master → out/<name>_final_4k.mp4. The JPEG frames and runs are deleted after a good master.
Output pixels match Remotion's (4K and draft): full-range BT.601 YUV (yuvj420p, smpte170m), h264 60 Mb/s
(VideoToolbox on a Mac, x264 elsewhere: vcut/hw.py). Keeps the computer awake while it runs.
Projects with faceKeys (moving face crop) are refused: use pipeline/tools/render_chunks.sh for those."""
from __future__ import annotations

import argparse, hashlib, json, os, shutil, subprocess, time
from pathlib import Path

import cv2
import numpy as np

from vcut import hw

W, H, S = 3840, 2160, 2  # output size; Remotion renders the 1920x1080 composition at --scale=2 (draft: 1280x720, 2/3)
CAM_AR = 16 / 9
DEFAULT_CARD = {"x": 0.7085, "y": 0.15, "w": 0.2735, "h": 0.69, "radius": 26, "faceX": 0.48, "top": 0.0, "zoom": 1.18}
ENC = hw.final_encoder_args("60M")
TO_OUT = "scale=out_color_matrix=bt601:out_range=pc,format=yuvj420p"
# Remotion's frames come out ~2 levels darker than a straight conversion, at every level and for both sources
# (fitted on flat areas of a real render, slope 1.00): match it, since the look is approved on Remotion drafts
MATCH = "lutrgb=r='clip(val-2,0,255)':g='clip(val-2,0,255)':b='clip(val-2,0,255)'"
SRC = Path()  # the cut files: out/ (4K) or out/proxy/ (draft)
SCR_FLAGS = os.environ.get("HY_SCR_FLAGS", "bilinear")  # Chrome upscales images bilinearly
CAM_FLAGS = os.environ.get("HY_CAM_FLAGS", "bicubic")  # face card: bilinear was 25% softer than Remotion, this is 1.02-1.06×
CAM_PARAMS = os.environ.get("HY_CAM_PARAMS", ":param0=0.1:param1=0.5")


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def rounded_mask(w: int, h: int, r: float, ss: int = 4) -> np.ndarray:
    """Anti-aliased rounded-rect alpha (0..255), supersampled."""
    m = np.zeros((h * ss, w * ss), np.uint8)
    R = int(r * ss)
    cv2.rectangle(m, (R, 0), (w * ss - 1 - R, h * ss - 1), 255, -1)
    cv2.rectangle(m, (0, R), (w * ss - 1, h * ss - 1 - R), 255, -1)
    for cx, cy in ((R, R), (w * ss - 1 - R, R), (R, h * ss - 1 - R), (w * ss - 1 - R, h * ss - 1 - R)):
        cv2.circle(m, (cx, cy), R, 255, -1)
    return cv2.resize(m, (w, h), interpolation=cv2.INTER_AREA)


def card_geometry(layout: dict) -> dict:
    """Main.tsx's card + CameraCrop maths in output pixels (Chrome snaps the clipping box to whole pixels)."""
    c = {**DEFAULT_CARD, **layout.get("card", {})}
    bw, bh = c["w"] * 1920, c["h"] * 1080  # CSS px
    vh = bh * c["zoom"]; vw = vh * CAM_AR
    left = min(0.0, max(bw - vw, bw / 2 - c["faceX"] * vw)); top = -c["top"] * vh
    x0, y0 = round(c["x"] * 1920 * S), round(c["y"] * 1080 * S)
    x1, y1 = round((c["x"] * 1920 + bw) * S), round((c["y"] * 1080 + bh) * S)
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0, "radius": c["radius"] * S,
            # the camera picture: scaled size and its offset inside the card box
            "vw": vw * S, "vh": vh * S, "vx": (c["x"] * 1920 + left) * S - x0, "vy": (c["y"] * 1080 + top) * S - y0}


def make_assets(out: Path, g: dict) -> None:
    mask = rounded_mask(g["w"], g["h"], g["radius"])
    cv2.imwrite(str(out / "card_mask.png"), mask)
    # box-shadow: 0 12px 40px rgba(0,0,0,0.35) at scale 2 → offset 24 px, blur radius 80 px = Gaussian sigma 40
    a = np.zeros((H, W), np.float32)
    full = rounded_mask(g["w"], g["h"], g["radius"]).astype(np.float32) / 255
    y = g["y"] + round(12 * S)
    a[y:y + g["h"], g["x"]:g["x"] + g["w"]] = full[: H - y]
    a = cv2.GaussianBlur(a, (0, 0), 20 * S) * 0.35
    rgba = np.zeros((H, W, 4), np.uint8)
    rgba[..., 3] = np.clip(a * 255 + 0.5, 0, 255).astype(np.uint8)
    cv2.imwrite(str(out / "card_shadow.png"), rgba)


def plain_cmd(P: Path, H_: Path, r: dict, g: dict, scr_wh: tuple[int, int], fps: float, dst: Path) -> list[str]:
    n = r["final1"] - r["final0"]
    ss = f"{r['cut0'] / fps:.6f}"
    sw, sh = scr_wh
    k = max(W / sw, H / sh)  # object-fit: cover
    cw, ch = round(sw * k), round(sh * k)
    vw, vh = round(g["vw"]), round(g["vh"])
    cx, cy = round(-g["vx"]), round(-g["vy"])
    f = (f"[0:v]scale={cw}:{ch}:flags={SCR_FLAGS}:in_color_matrix=bt709:in_range=tv,format=gbrp,"
         f"crop={W}:{H}:{(cw - W) // 2}:{(ch - H) // 2}[scr];")
    f += (f"[1:v]scale={vw}:{vh}:flags={CAM_FLAGS}{CAM_PARAMS}:in_color_matrix=bt709:in_range=tv,format=gbrp,"
          f"crop={g['w']}:{g['h']}:{cx}:{cy},format=gbrap[camc];[3:v]format=gray[m];"
          f"[camc][m]alphamerge[cam];"
          f"[scr][2:v]overlay=0:0:format=gbrp[sh];[sh][cam]overlay={g['x']}:{g['y']}:format=gbrp,{MATCH},{TO_OUT}[v]")
    return ["ffmpeg", "-v", "error", "-y", "-ss", ss, "-i", str(SRC / "screen_cut.mp4"), "-ss", ss, "-i",
            str(SRC / "talking_cut.mp4"), "-i", str(H_ / "card_shadow.png"), "-i", str(H_ / "card_mask.png"),
            "-filter_complex", f, "-map", "[v]", "-frames:v", str(n), "-r", f"{fps:g}", *ENC, str(dst)]


def remotion_cmd(H_: Path, r: dict, offset: int, fps: float, dst: Path) -> list[str]:
    """The run's frames from Remotion's JPEG sequence: the exact pictures its own encoder gets (yuvj420p, BT.601),
    so no colour conversion at all. (ProRes as the in-between added a ±1 level tint.)"""
    n = r["final1"] - r["final0"]
    return ["ffmpeg", "-v", "error", "-y", "-framerate", f"{fps:g}", "-start_number", str(offset), "-i",
            str(H_ / "frames/%06d.jpeg"), "-frames:v", str(n), *ENC, str(dst)]


def render_remotion(root: Path, rem: Path, n: int, props: str, conc: str, chunk: int, scale: str, jpeg_q: str) -> None:
    """FinalSubset frames as JPEGs, chunk by chunk (a crash loses one chunk; finished ones are skipped). Remotion pads
    the file names to the chunk's own digits (element-10.jpeg), so each chunk is renamed to 000010.jpeg."""
    rem.mkdir(exist_ok=True)
    tmp = rem.parent / "frames_tmp"
    for a in range(0, n, chunk):
        b = min(n, a + chunk) - 1
        if all((rem / f"{i:06d}.jpeg").exists() for i in (a, b)):
            continue
        cmd = [hw.npx(), "remotion", "render", "FinalSubset", str(tmp), "--sequence", "--image-format=jpeg", f"--frames={a}-{b}",
               f"--scale={scale}", f"--jpeg-quality={jpeg_q}", f"--concurrency={conc}", "--timeout=120000", f"--props={props}"]
        print(f"[hybrid] Remotion frames {a}-{b} of {n}", flush=True)
        for attempt in (1, 2):
            shutil.rmtree(tmp, ignore_errors=True)
            ok = subprocess.run(cmd, cwd=root / "remotion").returncode == 0
            hw.kill_headless_chrome(root)
            if ok:
                break
            if attempt == 2:
                raise SystemExit(f"Remotion failed twice on frames {a}-{b}; re-run to resume")
        for f in tmp.glob("element-*.jpeg"):
            f.rename(rem / f"{int(f.stem.split('-')[1]):06d}.jpeg")
        shutil.rmtree(tmp, ignore_errors=True)


def fingerprint(root: Path, P: Path, H_: Path, motion: str, props: str) -> str:
    """What the frames and runs were made from: if any of it changed (draft 2 after notes), they're stale."""
    h = hashlib.sha256(props.encode())
    srcs = [H_.parent / "hybrid/plan.json", P / "layout.json", P / motion, P / "edl.json", SRC / "screen_cut.mp4",
            SRC / "talking_cut.mp4", *sorted((root / "remotion/src").rglob("*.ts*"))]
    for f in srcs:
        if f.exists():
            st = f.stat()
            h.update(f"{f}:{st.st_size}:{st.st_mtime_ns}\n".encode() if f.suffix == ".mp4" else f.read_bytes())
    return h.hexdigest()


def main() -> None:
    global W, H, S, ENC, SRC
    ap = argparse.ArgumentParser()
    ap.add_argument("project"); ap.add_argument("--runs", default="", help="debug: encode only these run numbers")
    ap.add_argument("--motion", default="motion.json")
    ap.add_argument("--concurrency", default="", help="Remotion tabs (default: hardware.json, from cores and memory)")
    ap.add_argument("--draft", action="store_true", help="720p draft from the 720p proxies (out/proxy/)")
    ap.add_argument("--chunk", type=int, default=2000, help="Remotion frames per render (crash = one chunk lost)")
    ap.add_argument("--part", default="{}", help='a part of a long video: Final props, e.g. {"musicFrom": 320.4, "noFadeOut": true, "cardAfter": true}')
    ap.add_argument("--out", default="", help="final file name (default <project>_final_4k.mp4)")
    ap.add_argument("--no-master", action="store_true", help="parts: stop at the joined PCM .mov, master the whole video once")
    ap.add_argument("--keep", action="store_true", help="keep the JPEG frames and runs after the master")
    a = ap.parse_args()
    root = Path.cwd()
    P = root / "projects" / a.project / "out"
    SRC = P / "proxy" if a.draft else P
    if a.draft:
        W, H, S = 1280, 720, 2 / 3
        ENC = hw.final_encoder_args("4M")  # ~1/3 GB for 12 min; Remotion drafts are x264 crf 20 (~1.2 Mb/s)
    H_ = P / ("hybrid_draft" if a.draft else "hybrid"); H_.mkdir(exist_ok=True)
    conc = a.concurrency or str(hw.remotion_concurrency(a.draft))
    hw.keep_awake()
    tm: dict[str, float] = {}
    t = time.time()
    run(["uv", "run", "--project", "pipeline", "python", "pipeline/tools/hybrid_plan.py", a.project, a.motion])
    plan = json.loads((P / "hybrid/plan.json").read_text())  # FinalSubset reads it there, in both modes
    layout = json.loads((P / "layout.json").read_text())
    fps = plan["fps"]
    g = card_geometry(layout)
    make_assets(H_, g)
    props = json.dumps({"project": a.project, "motionFile": a.motion, **json.loads(a.part),
                        **({"proxy": True} if a.draft else {})})
    fp = fingerprint(root, P, H_, a.motion, props + " ".join(ENC))
    if (H_ / "inputs.txt").exists() and (H_ / "inputs.txt").read_text() != fp:
        print("[hybrid] the cut, layout, motion or Remotion code changed since the last run: starting the frames over")
        shutil.rmtree(H_ / "frames", ignore_errors=True)
        for f in H_.glob("run_*.mp4"):
            f.unlink()
    (H_ / "inputs.txt").write_text(fp)
    tm["plan"] = time.time() - t

    only = {int(x) for x in a.runs.split(",") if x}
    t = time.time()
    rem = H_ / "frames"
    nrem = len(plan["remotion_frames"])
    if nrem and not only:
        render_remotion(root, rem, nrem, props, conc, a.chunk, "0.6666666666666666" if a.draft else "2",
                        "92" if a.draft else "100")
    tm["remotion"] = time.time() - t
    print(f"[hybrid] Remotion: {nrem} frames in {tm['remotion']:.0f}s", flush=True)

    scr = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0", str(SRC / "screen_cut.mp4")], capture_output=True, text=True).stdout
    scr_wh = tuple(int(x) for x in scr.strip().split(","))
    t = time.time(); tp = tr = 0.0; offset = 0
    lst = []
    for i, r in enumerate(plan["runs"]):
        dst = H_ / f"run_{i:03d}.mp4"
        lst.append(f"file '{dst.as_posix()}'")
        n = r["final1"] - r["final0"]
        if (not only or i in only) and not dst.exists():
            t0 = time.time()
            tmp = H_ / "run_tmp.mp4"
            if r["kind"] == "ffmpeg":
                run(plain_cmd(P, H_, r, g, scr_wh, fps, tmp)); tp += time.time() - t0
            else:
                run(remotion_cmd(H_, r, offset, fps, tmp)); tr += time.time() - t0
            tmp.rename(dst)
            print(f"[hybrid] run {i} {r['kind']} {n} frames in {time.time() - t0:.0f}s "
                  f"({n / max(time.time() - t0, 1e-3):.0f} fps)", flush=True)
        if r["kind"] == "remotion":
            offset += n
    tm["encode_plain"], tm["encode_remotion"] = tp, tr
    if only:
        print(json.dumps(tm)); return

    t = time.time()
    (H_ / "list.txt").write_text("\n".join(lst) + "\n")
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(H_ / "list.txt"), "-c", "copy",
         str(H_ / "video.mp4")])
    part = json.loads(a.part)
    run(["uv", "run", "--project", "pipeline", "python", "pipeline/tools/hybrid_audio.py", a.project, "--motion", a.motion,
         "--out", str(H_ / "audio.wav"),
         *(["--music-from", str(part["musicFrom"])] if part.get("musicFrom") else []),
         *(["--no-fade-in"] if part.get("noFadeIn") else []), *(["--no-fade-out"] if part.get("noFadeOut") else []),
         *(["--card-after"] if part.get("cardAfter") else [])])
    run(["ffmpeg", "-v", "error", "-y", "-i", str(H_ / "video.mp4"), "-i", str(H_ / "audio.wav"), "-map", "0:v",
         "-map", "1:a", "-c:v", "copy", "-c:a", "pcm_s16le", str(H_ / "joined.mov")])
    tm["join_audio"] = time.time() - t
    if not a.no_master:
        t = time.time()
        dst = P / (a.out or f"{a.project}_{'draft_720p' if a.draft else 'final_4k'}.mp4")
        run(["uv", "run", "--project", "pipeline", "python", "-c",
             "import sys; from pathlib import Path; from vcut.master import master; "
             "print(master(Path(sys.argv[1]), Path(sys.argv[2])))", str(H_ / "joined.mov"), str(dst)])
        tm["master"] = time.time() - t
    tm["total"] = sum(tm.values())
    (H_ / "timing.json").write_text(json.dumps({k: round(v, 1) for k, v in tm.items()}, indent=1))
    print("[hybrid]", json.dumps({k: round(v) for k, v in tm.items()}))
    if not a.keep and not a.no_master:  # regenerable: the JPEG frames alone are ~2 MB each
        shutil.rmtree(rem, ignore_errors=True)
        for f in [*H_.glob("run_*.mp4"), H_ / "video.mp4", H_ / "audio.wav"]:
            f.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
