"""cut2src.py <project_dir> <cut_t>... — source time + the kept words around each cut-timeline time (and the join there)."""
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
e = json.loads((p / "out/edl.json").read_text())
ws = json.loads((p / "work/words.json").read_text())["words"]
for t in map(float, sys.argv[2:]):
    seg = max((s for s in e["segments"] if s["out_start_s"] <= t), key=lambda s: s["out_start_s"])
    src = seg["src_start_s"] + (t - seg["out_start_s"])
    near = [w for w in ws if abs(w["start"] - src) < 2.5]
    j = min(e["joins"], key=lambda j: abs(j["out_s"] - t))
    print(f"cut {t:.2f} → src {src:.2f} | nearest join {j['out_s']:.2f} cut={j.get('cut_text','')[:60]!r}")
    print("   ", " ".join(f"{w['i']}:{w['w']}@{w['start']:.2f}-{w['end']:.2f}" for w in near))
