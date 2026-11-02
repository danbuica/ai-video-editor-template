"""at.py <project_dir> MM:SS [before_s] [after_s] [--transcript out/transcript_cut.v1.json]
Words around a FINAL-video time (chapter cards included), with their src indices, ‖ where words were cut.
Review notes are on the draft that was watched: after a rebuild, pass that draft's backed-up transcript_cut (vN) and its
motion.json chapters still match closely enough to find the line."""
import json, sys
from pathlib import Path
args = [a for a in sys.argv[1:] if not a.startswith("--")]
pdir = Path(args[0]); m, s = args[1].split(":"); T = int(m) * 60 + float(s)
b = float(args[2]) if len(args) > 2 else 15; f = float(args[3]) if len(args) > 3 else 25
tf = sys.argv[sys.argv.index("--transcript") + 1] if "--transcript" in sys.argv else "out/transcript_cut.json"
cut = json.loads((pdir / tf).read_text())["words"]
mot = pdir / "out/motion.json"
plan = json.loads(mot.read_text()) if mot.exists() else {}
ch = [c["at"] for c in plan.get("chapters", []) if isinstance(c.get("at"), (int, float))]
card = plan.get("chapterSeconds", 2)
fin = lambda t: t + card * sum(1 for a in ch if a <= t)
mmss = lambda t: f"{int(t // 60)}:{t % 60:04.1f}"
line, last = [], None
for w in cut:
    F = fin(w["start"])
    if T - b <= F <= T + f:
        i = w["src_i"]
        if last is not None and i != last + 1: line.append("‖")
        line.append(f"{w['w']}[{i}]"); last = i
        if w["w"][-1:] in ".?!": print(mmss(F), " ".join(line)); line = []
if line: print("…", " ".join(line))
