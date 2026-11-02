# deps: uv run --with "opencv-python-headless<4.12" --with numpy python pipeline/tools/facetrack.py projects/<name>
"""facetrack.py <project_dir> — follow the face in the cut camera (720p proxy) so the face card stays centred.
Samples 2 fps, OpenCV Haar face → x centre (0..1 of the camera frame), median-smooths, holds a value until the face
drifts > THR, and moves at the nearest jump cut when one is close (else a 0.8 s ease). Writes out/face_track.json
as [{t, x}] keys (cut seconds); Main.tsx interpolates them for the card crop."""
import json, subprocess, sys
from pathlib import Path
import cv2, numpy as np
pdir = Path(sys.argv[1]); FPS = 2; THR = 0.015; SNAP = 2.0; EASE = 0.8
vid = pdir / "out/proxy/talking_cut.mp4"
W, H = 640, 360
p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(vid), "-vf", f"fps={FPS},scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "gray", "-"], stdout=subprocess.PIPE)
casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
xs = []
while True:
    buf = p.stdout.read(W * H)
    if len(buf) < W * H: break
    g = np.frombuffer(buf, np.uint8).reshape(H, W)
    f = casc.detectMultiScale(g, 1.1, 5, minSize=(50, 50))
    if len(f):
        x, y, w, h = max(f, key=lambda r: r[2] * r[3])
        xs.append((x + w / 2) / W)
    else:
        xs.append(np.nan)
xs = np.array(xs)
t = np.arange(len(xs)) / FPS
ok = ~np.isnan(xs)
xs = np.interp(t, t[ok], xs[ok])
k = 9 * FPS  # 9 s median
sm = np.array([np.median(xs[max(0, i - k // 2): i + k // 2 + 1]) for i in range(len(xs))])
edl = json.loads((pdir / "out/edl.json").read_text())
joins = np.array([j["out_s"] for j in edl["joins"] if j.get("kind") not in ("head", "tail")])
keys = [{"t": 0.0, "x": round(float(sm[0]), 4)}]
held = sm[0]
i = 0
while i < len(sm):
    if abs(sm[i] - held) > THR:
        # settle: the value a few seconds on
        new = float(np.median(sm[i: i + 4 * FPS]))
        tc = t[i]
        near = joins[np.abs(joins - tc) < SNAP] if len(joins) else []
        if len(near):
            tj = float(near[np.argmin(np.abs(near - tc))])
            keys += [{"t": round(tj - 0.001, 3), "x": round(float(held), 4)}, {"t": round(tj, 3), "x": round(new, 4)}]
        else:
            keys += [{"t": round(tc - EASE / 2, 3), "x": round(float(held), 4)}, {"t": round(tc + EASE / 2, 3), "x": round(new, 4)}]
        held = new
        i += 4 * FPS
    else:
        i += 1
(pdir / "out/face_track.json").write_text(json.dumps(keys))
print(f"{len(xs)} samples, x range {xs.min():.3f}-{xs.max():.3f}, {len(keys)} keys")
