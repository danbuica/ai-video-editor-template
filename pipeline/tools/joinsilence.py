"""joinsilence.py <project_dir> [cut.wav] — real silence kept at every pause/cut join (from the cut audio), by join kind."""
import json, sys, numpy as np, soundfile as sf
from pathlib import Path
p = Path(sys.argv[1]); wav = sys.argv[2] if len(sys.argv) > 2 else str(p / "work/cut_master.wav")
e = json.loads((p / "out/edl.json").read_text())
x, sr = sf.read(wav, always_2d=True, dtype="float32"); x = x.mean(1)
h = int(0.01 * sr); n = len(x) // h
db = 20 * np.log10(np.sqrt((x[: n * h].reshape(n, h) ** 2).mean(1)) + 1e-9)
floor = np.percentile(db, 8); q = floor + 12
out = {}
for j in e["joins"]:
    if j["kind"] in ("head", "tail"): continue
    c = int(j["out_s"] / 0.01)
    if c >= n: continue
    a = c
    while a > 0 and db[a - 1] < q and c - a < 300: a -= 1
    b = c
    while b < n and db[b] < q and b - c < 300: b += 1
    kind = "mid" if j.get("mid_sentence") else j["kind"] if j["kind"] in ("pause",) else "cut"
    out.setdefault(kind, []).append(((b - a) * 0.01, j["out_s"], j.get("reason", "")[:40]))
for k, v in out.items():
    s = sorted(t for t, _, _ in v)
    print(f"{k:6} n={len(s):4} median={s[len(s)//2]:.2f}s p90={s[int(len(s)*.9)]:.2f}s >0.35s: {sum(1 for t in s if t > 0.35)}")
if len(sys.argv) > 3:
    allj = sorted(((t, s, r) for v in out.values() for t, s, r in v), reverse=True)[: int(sys.argv[3])]
    jm = {round(j["out_s"], 2): j for j in e["joins"]}
    for t, s, r in allj:
        j = jm.get(round(s, 2), {})
        print(f"  {s:7.1f}s kept {t:.2f}s  {j.get('kind',''):12} ...{j.get('text_before','')[-28:]} ‖ {j.get('text_after','')[:28]}")
