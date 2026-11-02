"""List gaps between consecutive KEPT words (same keep range) that contain speech-level sound."""
import json, sys, numpy as np, soundfile as sf
from pathlib import Path
pdir = Path(sys.argv[1])
ws = json.loads((pdir / "work/words.json").read_text())["words"]
ranges = []
for line in (pdir / "keeps.txt").read_text().splitlines():
    p = line.split(maxsplit=2)
    if len(p) >= 2 and p[0].isdigit(): ranges.append((int(p[0]), int(p[1])))
x, sr = sf.read(str(pdir / "work/asr16k.wav"), dtype="float32")
h = int(0.02 * sr)
n = len(x) // h
db = 20 * np.log10(np.sqrt((x[: n * h].reshape(n, h) ** 2).mean(1)) + 1e-9)
thr = float(sys.argv[2]) if len(sys.argv) > 2 else -38
for a, b in ranges:
    for k in range(a, b):
        w, v = ws[k], ws[k + 1]
        g0, g1 = w["end"] + 0.15, v["start"] - 0.15
        if g1 - g0 < 0.3: continue
        seg = db[int(g0 / 0.02): int(g1 / 0.02)]
        loud = (seg > thr).sum() * 0.02
        if loud >= float(sys.argv[3] if len(sys.argv) > 3 else 0.3):
            print(f"{k}->{k+1} {w['end']:.2f}-{v['start']:.2f} gap {v['start']-w['end']:.1f}s loud {loud:.2f}s  ...{w['w']} | {v['w']}...")
