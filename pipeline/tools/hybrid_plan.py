"""Fast 4K final, step 1: split the Final timeline into "plain" runs (screen + face card, nothing on
top: ffmpeg can draw them) and "fancy" runs (full-screen head, graphics, images, demos, zooms, phones, blurs, chapter
cards: Remotion draws them).

Replicates Main.tsx / Final.tsx / resolvePlan exactly (same float comparisons, same rounding):
  uv run --project pipeline python pipeline/tools/hybrid_plan.py <name>      → projects/<name>/out/hybrid/plan.json"""
from __future__ import annotations

import json, math, sys
from pathlib import Path

name = sys.argv[1]
OUT = Path("projects") / name / "out"
edl = json.loads((OUT / "edl.json").read_text())
layout = json.loads((OUT / "layout.json").read_text())
motion_file = sys.argv[2] if len(sys.argv) > 2 else "motion.json"
plan = json.loads((OUT / motion_file).read_text()) if (OUT / motion_file).exists() else {"items": []}
words = json.loads((OUT / "transcript_cut.json").read_text())["words"]
fps = edl["fps_float"]
total = edl["out_frames"]

by_src = {w["src_i"]: w for w in words}
jsround = lambda x: math.floor(x + 0.5)  # JS Math.round (Python rounds 62.5 to 62)


def tref(r):
    if isinstance(r, (int, float)):
        return float(r)
    w = by_src.get(r["w"]) or next((x for x in words if x["src_i"] > r["w"]), words[-1])
    return (w["end"] if r.get("end") else w["start"]) + r.get("pad", 0)


items = [{**it, "from": tref(it["from"]), "to": tref(it["to"])} for it in plan.get("items", [])]
full_ranges = layout.get("full", []) + [{"from": it["from"], "to": it["to"]} for it in items
                                        if it.get("fullscreen") or it["type"].startswith("scene-")]
# blurs hide secrets: Remotion draws them until the ffmpeg frosted box has been checked against it on a real project
others = [layout.get(k, []) for k in ("images", "demos", "zooms", "blurs")]
# phones float over the full-screen head only, but PhoneLayer mounts always: treat their whole span as fancy
phones = layout.get("phones", [])
if layout.get("faceKeys"):
    raise SystemExit("faceKeys (moving face crop) aren't drawn by the ffmpeg path yet: render this project with "
                     "pipeline/tools/render_chunks.sh instead")


def cut_fancy(f: int) -> str | None:
    t = f / fps
    if any(t >= r["from"] and t < r["to"] for r in full_ranges):
        return "full"
    for kind, rs in zip(("image", "demo", "zoom", "blur"), others):
        if any(t >= r["from"] and t < r["to"] for r in rs):
            return kind
    if any(t >= p["from"] - 1 and t < p["to"] + 1 for p in phones):
        return "phone"
    return None


card_frames = jsround(plan.get("chapterSeconds", 2) * fps)
chapters = sorted(({"at": jsround(tref(c["at"]) * fps), "number": c["number"]} for c in plan.get("chapters", [])),
                  key=lambda c: c["at"])
bounds = [0] + [c["at"] for c in chapters] + [total]
segments = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]

# walk Final's Series: [segment 0] [card 1] [segment 1] [card 2] ...
frames = []  # per final frame: ("card", None) | ("fancy", cut) | ("plain", cut)
for i, (s, e) in enumerate(segments):
    if i > 0:
        frames += [("card", None)] * card_frames
    for f in range(s, e):
        frames.append(("fancy" if cut_fancy(f) else "plain", f))

runs = []
for F, (kind, cut) in enumerate(frames):
    k = "remotion" if kind in ("card", "fancy") else "ffmpeg"
    r = runs[-1] if runs else None
    contiguous = r and r["kind"] == k and (k == "remotion" or cut == r["cut1"])
    if contiguous:
        r["final1"] = F + 1
        if k == "ffmpeg":
            r["cut1"] = cut + 1
    else:
        runs.append({"kind": k, "final0": F, "final1": F + 1, "cut0": cut, "cut1": None if cut is None else cut + 1})

n_plain = sum(r["final1"] - r["final0"] for r in runs if r["kind"] == "ffmpeg")
res = {"project": name, "fps": fps, "final_frames": len(frames), "plain_frames": n_plain,
       "plain_pct": round(100 * n_plain / len(frames), 1), "runs": runs,
       "remotion_frames": [F for F, fr in enumerate(frames) if fr[0] != "plain"]}
(OUT / "hybrid").mkdir(exist_ok=True)
(OUT / "hybrid" / "plan.json").write_text(json.dumps(res))
print(f"{name}: {len(frames)} final frames, {n_plain} plain ({res['plain_pct']}%), "
      f"{sum(r['kind'] == 'ffmpeg' for r in runs)} ffmpeg runs, {sum(r['kind'] == 'remotion' for r in runs)} Remotion runs")
for r in runs:
    print(f"  {r['kind']:8} final {r['final0']:6}-{r['final1']:6} ({(r['final1'] - r['final0']) / fps:6.1f}s)"
          + (f" cut {r['cut0']}-{r['cut1']}" if r["kind"] == "ffmpeg" else ""))
