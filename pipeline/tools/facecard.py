# deps: uv run --no-project --with "opencv-python-headless==4.10.0.84" --with "numpy<2.3" python pipeline/tools/facecard.py projects/<name>
"""facecard.py <project_dir> [--check] [--edge 0.746] [--dry] — size the face card to the recording and frame the speaker in it.

Measures, then writes layout.json `card` (radius and other keys kept):
  - the app window's right edge on the screen recording (columns that are wallpaper-blue in most rows), so the
    card fills the empty strip with MARGIN px on each side, and runs taller than before (CARD_Y/CARD_H);
  - the speaker's face in the camera (OpenCV Haar, ~2 samples/s, medians): faceX centres him, zoom makes the face FACE of the
    card height, top puts the face centre at EYE of the card height (headroom).
Then always checks: crops the camera exactly like CameraCrop (lib/camera.tsx, faceKeys followed) at CHECKS times
across the cut, finds the face inside the card and writes out/face_check.png (centre line + target line) with the
median offset. Median off by more than TOL of the card width = not centred: fix it (facetrack.py for drift) before a draft.
--check only runs the check on the current layout.json (no measuring, no writing)."""
import argparse, json, subprocess
from pathlib import Path
import cv2, numpy as np

MARGIN = 28  # px between the app window, the card and the frame edge
CARD_Y, CARD_H = 0.07, 0.86  # a big card: a small one makes viewers squint at the face
FACE = 0.36  # face box height / card height
EYE = 0.40  # face centre / card height
CHECKS = 12
TOL = 0.04  # median face offset allowed, of the card width
FLAG = 0.10  # one sample this far off is drawn red (a head turn is ~5-10%)
W, H = 640, 360
CASC = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")


def src(pdir: Path, name: str) -> Path:
    p = pdir / "out/proxy" / name
    return p if p.exists() else pdir / "out" / name


def duration(p: Path) -> float:
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)]))


def frame_at(p: Path, t: float, w: int = W, h: int = H, gray=False) -> np.ndarray:
    fmt, ch = ("gray", 1) if gray else ("bgr24", 3)
    buf = subprocess.check_output(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(p), "-frames:v", "1", "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", fmt, "-"])
    return np.frombuffer(buf, np.uint8).reshape(h, w, ch) if ch == 3 else np.frombuffer(buf, np.uint8).reshape(h, w)


def biggest_face(g: np.ndarray, min_px: int = 40):
    f = CASC.detectMultiScale(g, 1.1, 5, minSize=(min_px, min_px))
    return max(f, key=lambda r: r[2] * r[3]) if len(f) else None


def window_edge(pdir: Path) -> float:
    """x (0..1) where the wallpaper strip on the right starts: scan from the right while columns stay wallpaper-blue."""
    p = src(pdir, "screen_cut.mp4")
    d = duration(p)
    blue = np.zeros(W)
    n = 24
    for t in np.linspace(0.5, max(0.6, d - 0.5), n):
        hsv = cv2.cvtColor(frame_at(p, t), cv2.COLOR_BGR2HSV)
        is_blue = (hsv[..., 0] >= 85) & (hsv[..., 0] <= 135) & (hsv[..., 1] >= 25) & (hsv[..., 2] >= 40)
        blue += is_blue.mean(axis=0) >= 0.75
    wall = blue / n >= 0.5  # in at least half the frames (a full-screen window or a scene can cover it for a while)
    x = W - 4  # the last few columns can be a dark frame edge after scaling
    while x > 0 and wall[x - 1]:
        x -= 1
    if x == W - 4:
        raise SystemExit("no wallpaper strip found on the right of the screen recording: pass --edge")
    return x / W


def face_stats(pdir: Path):
    p = src(pdir, "talking_cut.mp4")
    d = duration(p)
    fps = min(2.0, 600 / d)  # ~2/s, at most 600 samples
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(p), "-vf", f"fps={fps},scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "gray", "-"], stdout=subprocess.PIPE)
    rows = []
    while True:
        buf = proc.stdout.read(W * H)
        if len(buf) < W * H:
            break
        r = biggest_face(np.frombuffer(buf, np.uint8).reshape(H, W), 50)
        if r is not None:
            x, y, w, h = r
            rows.append(((x + w / 2) / W, (y + h / 2) / H, h / H))
    if not rows:
        raise SystemExit("no face found in the camera")
    a = np.array(rows)
    k = min(len(a), 18)  # ~9 s rolling median: sideways drift, not head turns
    roll = np.array([np.median(a[max(0, i - k // 2): i + k // 2 + 1, 0]) for i in range(len(a))])
    return np.median(a, axis=0), np.percentile(roll, [10, 90]), len(rows)


def face_at(layout: dict, t: float) -> float:
    k = layout.get("faceKeys") or []
    if not k:
        return layout["card"]["faceX"]
    if t <= k[0]["t"]:
        return k[0]["x"]
    for a, b in zip(k, k[1:]):
        if t < b["t"]:
            u = (t - a["t"]) / (b["t"] - a["t"])
            u = 4 * u ** 3 if u < 0.5 else 1 - (-2 * u + 2) ** 3 / 2  # Easing.inOut(cubic), like Main.tsx
            return a["x"] + (b["x"] - a["x"]) * u
    return k[-1]["x"]


def check(pdir: Path, layout: dict) -> float:
    """Crop like CameraCrop at CHECKS times, find the face in the card, tile out/face_check.png. Returns the offsets."""
    c = layout["card"]
    p = src(pdir, "talking_cut.mp4")
    d = duration(p)
    S = 0.5  # check at half size
    bw, bh = round(c["w"] * 1920 * S), round(c["h"] * 1080 * S)
    tiles, dxs = [], []
    for t in np.linspace(0.5, max(0.6, d - 0.5), CHECKS):
        cam = frame_at(p, t, 1280, 720)
        vh = bh * c["zoom"]
        vw = vh * 16 / 9
        left = min(0.0, max(bw - vw, bw / 2 - face_at(layout, t) * vw))
        top = -c["top"] * vh
        img = cv2.resize(cam, (round(vw), round(vh)), interpolation=cv2.INTER_AREA)
        x0, y0 = round(-left), round(-top)
        crop = img[y0:y0 + bh, x0:x0 + bw].copy()
        if crop.shape[0] < bh:  # past the bottom of the camera
            crop = cv2.copyMakeBorder(crop, 0, bh - crop.shape[0], 0, 0, cv2.BORDER_CONSTANT)
        r = biggest_face(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), 30)
        cv2.line(crop, (bw // 2, 0), (bw // 2, bh), (255, 225, 34), 1)
        cv2.line(crop, (0, round(EYE * bh)), (bw, round(EYE * bh)), (255, 225, 34), 1)
        if r is not None:
            x, y, w, h = r
            dx = (x + w / 2) / bw - 0.5
            dxs.append(dx)
            ok = abs(dx) <= FLAG
            cv2.rectangle(crop, (x, y), (x + w, y + h), (80, 220, 80) if ok else (60, 60, 255), 2)
            label = f"{t:6.1f}s dx {dx * 100:+.1f}%"
        else:
            label = f"{t:6.1f}s no face"
        cv2.putText(crop, label, (8, bh - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA)
        tiles.append(crop)
    cols = 6
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    sheet = np.vstack([np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)])
    cv2.imwrite(str(pdir / "out/face_check.png"), sheet)
    return dxs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--check", action="store_true", help="only check the current layout.json")
    ap.add_argument("--edge", type=float, help="app window right edge (0..1), when the wallpaper isn't blue")
    ap.add_argument("--dry", action="store_true", help="print the card, don't write layout.json")
    a = ap.parse_args()
    pdir = Path(a.project)
    lp = pdir / "out/layout.json"
    layout = json.loads(lp.read_text()) if lp.exists() else {"full": [], "punchIn": 1.12}
    base = {"x": 0.7085, "y": 0.15, "w": 0.2735, "h": 0.69, "radius": 26, "faceX": 0.48, "top": 0.0, "zoom": 1.18}  # DEFAULT_CARD
    layout["card"] = {**base, **layout.get("card", {})}
    if not a.check:
        edge = a.edge if a.edge is not None else window_edge(pdir)
        (fx, fy, fh), (x10, x90), n = face_stats(pdir)
        x = edge + MARGIN / 1920
        w = 1 - MARGIN / 1920 - x
        zoom = float(np.clip(FACE / fh, 1.0, 2.2))
        top = float(np.clip(fy - EYE / zoom, 0.0, 1 - 1 / zoom))
        card = {"x": round(x, 4), "y": CARD_Y, "w": round(w, 4), "h": CARD_H, "faceX": round(float(fx), 4), "top": round(top, 4), "zoom": round(zoom, 3)}
        print(f"window edge {edge:.3f} → card x {card['x']} w {card['w']} ({w * 1920:.0f}×{CARD_H * 1080:.0f} px)")
        print(f"face ({n} samples): x {fx:.3f} (10-90% {x10:.3f}-{x90:.3f}), y {fy:.3f}, height {fh:.3f} of the camera → zoom {zoom:.2f}, top {top:.3f}")
        if x90 - x10 > 0.03:
            print("  his 9 s median moves sideways more than 3% of the frame: run pipeline/tools/facetrack.py and load out/face_track.json as layout.faceKeys")
        if w * 1920 < 340:
            print(f"  WARN: only {w * 1920:.0f} px of wallpaper on the right, the card will be narrow")
        layout["card"].update(card)
    dxs = check(pdir, layout)
    if not dxs:
        raise SystemExit("check: no face found inside the card: look at out/face_check.png")
    med = float(np.median(dxs))
    if not a.check and abs(med) > 0.01:
        # the camera-wide median and the face inside the crop can differ by a few %: nudge faceX (and faceKeys) by what
        # the check saw, then check again
        c = layout["card"]
        shift = med * (c["w"] * 1920) / (c["h"] * 1080 * c["zoom"] * 16 / 9)
        c["faceX"] = round(c["faceX"] + shift, 4)
        for k in layout.get("faceKeys") or []:
            k["x"] = round(k["x"] + shift, 4)
        print(f"nudge: face {med * 100:+.1f}% off in the card → faceX {c['faceX']}")
        dxs = check(pdir, layout)
        med = float(np.median(dxs)) if dxs else med
    if not a.check and not a.dry:
        lp.write_text(json.dumps(layout, indent=2) + "\n")
        print(f"wrote {lp}")
    verdict = "centred" if abs(med) <= TOL else "NOT CENTRED: fix before the draft"
    print(f"check: median face offset {med * 100:+.1f}% of the card width ({verdict}), {sum(abs(d) > FLAG for d in dxs)}/{len(dxs)} "
          f"samples past {FLAG * 100:.0f}% (head turns) → {pdir / 'out/face_check.png'}")
    if abs(med) > TOL:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
