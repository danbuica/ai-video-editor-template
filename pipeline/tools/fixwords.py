"""fixwords.py <project_dir> <i0> <i1> <spec>  — replace words i0..i1 (inclusive) in work/words.json with
spec = "w@start-end w@start-end ..." (use _ for spaces inside a word). Renumbers 'i' and shifts keeps.txt
indices > i1 by the length change. Backs up words.json once per call."""
import json, re, shutil, sys, time
from pathlib import Path
pdir, i0, i1, spec = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
wf = pdir / "work/words.json"
shutil.copy(wf, pdir / f"work/words.bak.{int(time.time())}.json")
d = json.loads(wf.read_text()); ws = d["words"]
seg = ws[i0]["seg"]
new = []
for tok in spec.split():
    m = re.fullmatch(r"(.+)@([\d.]+)-([\d.]+)", tok)
    w, a, b = m.group(1).replace("_", " "), float(m.group(2)), float(m.group(3))
    new.append({"w": w, "start": a, "end": b, "score": 0.9, "seg": seg, "fixed": True})
delta = len(new) - (i1 - i0 + 1)
ws[i0:i1 + 1] = new
for k, x in enumerate(ws): x["i"] = k
wf.write_text(json.dumps(d, ensure_ascii=False, indent=1))
kf = pdir / "keeps.txt"
if kf.exists() and delta:
    out = []
    for line in kf.read_text().splitlines():
        p = line.split(maxsplit=2)
        if len(p) >= 2 and p[0].isdigit() and p[1].isdigit():
            a, b = int(p[0]), int(p[1])
            a = a + delta if a > i1 else a
            b = b + delta if b > i1 else (b if b < i0 else b)
            line = " ".join([str(a), str(b)] + p[2:])
        out.append(line)
    kf.write_text("\n".join(out) + "\n")
print(f"replaced {i0}..{i1} with {len(new)} words (delta {delta:+d})")
