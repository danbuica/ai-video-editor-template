"""Parts of a long video: give each part of a long video its own layout.json + motion.json, cut from the full project's.

  uv run --project pipeline python pipeline/tools/parts_split.py <name> <name>_p1 <name>_p2

Before that, after `vcut keep` of the full project and of every part (and `vcut edl` of the full one):
  uv run --project pipeline python pipeline/tools/parts_split.py edges <name> <name>_p1 <name>_p2
writes head_at / tail_at into each part's decisions.json, so the parts start and end exactly where the one-video cut
joins them (p1 + p2 = the full cut, frame for frame; without it p1 kept the 0.5 s "end of video" tail, +6 frames).

Run after `vcut build` of every part (needs each part's out/transcript_cut.json). Layout ranges (cut seconds) are moved
onto the part's own timeline and clipped to it; graphics, SFX and chapters stay with the part that holds their anchor
word (word refs keep working: all parts share the full project's words.json); a chapter that opens a part goes to 0.
Prints the music offset (seconds into the bed) each part needs so the bed runs on across the join."""
from __future__ import annotations

import bisect, json, math, sys
from pathlib import Path


def edges(full: str, parts: list[str]) -> None:
    root = Path("projects")
    edl = json.loads((root / full / "out/edl.json").read_text())
    segs, fps = edl["segments"], edl["fps_float"]
    words = json.loads((root / full / "work/words.json").read_text())["words"]
    dec = [json.loads((root / n / "work/decisions.json").read_text()) for n in parts]
    seg_of = lambda t: next((s for s in segs if s["src_start_s"] <= t < s["src_end_s"]), None)
    at: list[dict] = [{} for _ in parts]
    for k in range(len(parts) - 1):
        wa, wb = dec[k]["_keeps"][-1][1], dec[k + 1]["_keeps"][0][0]
        a, b = seg_of(words[wa]["start"]), seg_of(words[wb]["start"])
        if a is None or b is None:
            raise SystemExit(f"the full cut doesn't keep word {wa} or {wb}: run `vcut keep` + `vcut edl` on the full "
                             "project with the same keep-list first")
        if a is b:  # one continuous take across the split: cut in the middle of the pause, on a frame
            t = round((words[wa]["end"] + words[wb]["start"]) / 2 * fps) / fps
            at[k]["tail_at"], at[k + 1]["head_at"] = t, t
        else:  # the full cut joins here: each part keeps exactly its side of that join
            at[k]["tail_at"], at[k + 1]["head_at"] = a["src_end_s"], b["src_start_s"]
    for name, d, e in zip(parts, dec, at):
        for key in ("head_at", "tail_at"):
            d["settings"].pop(key, None)
        d["settings"].update(e)
        (root / name / "work/decisions.json").write_text(json.dumps(d, indent=1))
        print(f"{name}: {e}")


if sys.argv[1] == "edges":
    edges(sys.argv[2], sys.argv[3:])
    sys.exit()

full, parts = sys.argv[1], sys.argv[2:]
F = Path("projects") / full / "out"
layout = json.loads((F / "layout.json").read_text())
motion = json.loads((F / "motion.json").read_text())
flist = json.loads((F / "transcript_cut.json").read_text())["words"]
fwords = {w["src_i"]: w for w in flist}
fstarts = [w["start"] for w in flist]
fps = json.loads((F / "edl.json").read_text())["fps_float"]
jsround = lambda x: math.floor(x + 0.5)
card_s = jsround(motion.get("chapterSeconds", 2) * fps) / fps

spans = []  # (first, last) word of every part
for name in parts:
    ws = json.loads((Path("projects") / name / "out/transcript_cut.json").read_text())["words"]
    spans.append((ws[0]["src_i"], ws[-1]["src_i"]))
music_from = 0.0
for k, name in enumerate(parts):
    P = Path("projects") / name / "out"
    words = json.loads((P / "transcript_cut.json").read_text())["words"]
    edl = json.loads((P / "edl.json").read_text())
    dur = edl["out_frames"] / fps
    lo, hi = words[0]["src_i"], words[-1]["src_i"]
    pw = {w["src_i"]: w for w in words}
    off = fwords[lo]["start"] - words[0]["start"]
    drift = max(abs((fwords[w["src_i"]]["start"] - off) - w["start"]) for w in words)

    def to_part(T: float) -> float | None:
        """A time on the full cut → the part's cut, anchored on the word just before it (the full project's layout may
        come from an older build of the cut, so one constant offset drifts; up to 16 s seen)."""
        i = bisect.bisect_right(fstarts, T) - 1
        if i < 0:
            return 0.0 if k == 0 else None
        w = flist[i]
        if w["src_i"] < lo:
            return 0.0 if flist[min(i + 1, len(flist) - 1)]["src_i"] >= lo else None
        if w["src_i"] > hi:
            return None
        return pw[w["src_i"]]["start"] + min(T - w["start"], 10.0) if w["src_i"] in pw else None

    def shift(rs):
        out = []
        for r in rs or []:
            a, b = to_part(r["from"]), to_part(r["to"])
            if a is None and b is None:
                continue
            a = 0.0 if a is None else a
            b = dur if b is None else b
            if b <= a or b <= 0 or a >= dur:
                continue
            out.append({**r, "from": round(max(0.0, a), 3), "to": round(min(dur, b), 3)})
        return out

    L = {**layout}
    for key in ("full", "images", "zooms", "blurs", "phones", "demos"):
        if key in L:
            L[key] = shift(L[key])
    if L.get("faceKeys"):
        L["faceKeys"] = [{**f, "t": round(to_part(f["t"]), 3)} for f in L["faceKeys"] if to_part(f["t"]) is not None]
    inside = lambda ref: isinstance(ref, dict) and lo <= ref["w"] <= hi
    M = {**motion, "items": [it for it in motion["items"] if inside(it["from"])],
         "chapters": [({**c, "at": 0} if c["at"]["w"] <= lo else c) for c in motion.get("chapters", []) if inside(c["at"])
                      or (k > 0 and c["at"]["w"] == lo)]}
    (P / "layout.json").write_text(json.dumps(L, indent=1))
    (P / "motion.json").write_text(json.dumps(M, indent=1))
    final_s = dur + len(M["chapters"]) * card_s
    # hybrid_render.py --part: the bed runs on across joins, no fades inside, the music rises into the next part's card
    card_after = k + 1 < len(parts) and any(hi < c["at"]["w"] <= spans[k + 1][0] for c in motion.get("chapters", []))
    part = {"musicFrom": round(music_from, 3), **({"noFadeIn": True} if k else {}),
            **({"noFadeOut": True} if k + 1 < len(parts) else {}), **({"cardAfter": True} if card_after else {})}
    print(f"{name}: words {lo}-{hi}, cut {dur:.2f} s, offset {off:.3f} s (constant-offset drift would be {drift:.1f} s), "
          f"full ranges {[(r['from'], r['to']) for r in L['full']]}, images {[(r['from'], r['to']) for r in L.get('images', [])]}, "
          f"{len(M['items'])} graphics, chapters {[c['number'] for c in M['chapters']]}, final {final_s:.2f} s, "
          f"music from {music_from:.2f} s\n  render: hybrid_render.py {name} --no-master --part '{json.dumps(part)}'")
    music_from += final_s
