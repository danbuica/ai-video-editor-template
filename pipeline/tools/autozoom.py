"""Auto-zooms on the screen recording when the speaker points at something ("click on Connect", "right here").

  uv run --project pipeline --with pyobjc-framework-Vision --with pyobjc-framework-Quartz \
      --with "opencv-python-headless<4.12" python pipeline/tools/autozoom.py <name> [--from 150 --to 270]

1. Triggers from the final transcript (cut seconds): "click/clicking/press/tap/select/hit (on) <target>", "type (in) <target>",
   "open <target>" → a NAMED target; "right here", "over here", "this one here", "look (at)" → an UNNAMED one.
2. Where on screen (screen_cut.mp4 = the cut timeline), in this order:
   a. named target: OCR (macOS Vision) of the frame at the word, the matching box nearest the mouse pointer;
   b. the mouse pointer itself (template match, pipeline/tools/cursors);
   c. nothing found → no zoom (logged). (A "what changed after the word" fallback was tried and dropped: 1 of 5 right
      on an unseen stretch, it grabs streaming text.)
3. A zoom = layout `zooms` entry Main.tsx already draws: push in (0.6 s ease) to ~1.6× around the target, hold to the end of
   the sentence (2.5-5 s), ease out; OCR targets also get a `marks` box. Only on plain frames (no graphics, full-screen
   head, images, demos, phones: pipeline/tools/hybrid_plan.py), at most one per 8 s.
Writes out/layout_autozoom.json (layout + zooms) and out/autozoom.md (every trigger: what was said, what was found)."""
from __future__ import annotations

import argparse, json, re, subprocess, tempfile
from pathlib import Path

import cv2
import numpy as np

NAMED = {"click", "clicking", "clicked", "press", "pressing", "tap", "select", "hit", "type", "typing"}  # not "open": "keep this open"
SKIP = {"on", "in", "the", "this", "that", "these", "those", "a", "an", "into", "onto", "to", "again", "just"}
STOP_AFTER = {"and", "then", "to", "so", "it", "or", "but", "which", "will", "and", "button", "right", "here", "now"}
UNNAMED = [("right", "here"), ("over", "here"), ("one", "here"), ("look", "at"), ("look", "what"), ("in", "here")]
GENERIC = {"button", "buttons", "icon", "icons", "it", "one", "link", "tab", "option", "here", "there", "them"}
MIN_GAP, SCALE = 8.0, 1.6


def norm(w: str) -> str:
    return re.sub(r"[^a-z0-9/]", "", w.lower())


def triggers(words: list[dict]) -> list[dict]:
    out = []
    n = len(words)
    for i, w in enumerate(words):
        t = norm(w["w"])
        if t in NAMED:
            j = i + 1
            while j < n and norm(words[j]["w"]) in SKIP:
                j += 1
            tgt = []
            while j < n and len(tgt) < 3:
                k = norm(words[j]["w"])
                if not k or k in STOP_AFTER:
                    break
                tgt.append(words[j]["w"].strip(".,!?:;\"'"))
                if re.search(r"[.,!?:;]$", words[j]["w"]):
                    break
                j += 1
            if tgt and all(norm(x) in GENERIC for x in tgt):
                tgt = []  # "click on these buttons": no name to read, find it by what changes
            if t in ("open",) and not tgt:
                continue
            out.append({"i": i, "t": w["start"], "say": " ".join(x["w"] for x in words[max(0, i - 3): i + 6]),
                        "target": " ".join(tgt) or None, "verb": t})
        for a, b in UNNAMED:
            if t == a and i + 1 < n and norm(words[i + 1]["w"]) == b:
                out.append({"i": i, "t": w["start"], "say": " ".join(x["w"] for x in words[max(0, i - 4): i + 5]),
                            "target": None, "verb": f"{a} {b}"})
    out.sort(key=lambda x: x["t"])
    return out


def sentence_end(words: list[dict], i: int) -> float:
    for j in range(i, min(len(words), i + 25)):
        if re.search(r"[.!?]$", words[j]["w"]):
            return words[j]["end"]
    return words[min(len(words) - 1, i + 12)]["end"]


def frame_at(video: Path, t: float, tmp: Path, tag: str) -> np.ndarray:
    p = tmp / f"{tag}.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", str(p)], check=True)
    return cv2.imread(str(p))


def ocr_boxes(png: Path) -> list[tuple[str, float, tuple[float, float, float, float]]]:
    """(text, confidence, (x, y, w, h) as fractions of the image, origin top-left)."""
    import Vision
    from Foundation import NSURL
    req = Vision.VNRecognizeTextRequest.alloc().init(); req.setRecognitionLevel_(0); req.setUsesLanguageCorrection_(False)
    Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(str(png)), None).performRequests_error_([req], None)
    res = []
    for r in req.results() or []:
        c = r.topCandidates_(1)[0]
        bb = r.boundingBox()
        res.append((str(c.string()), float(c.confidence()),
                    (bb.origin.x, 1 - bb.origin.y - bb.size.height, bb.size.width, bb.size.height)))
    return res


def match_text(target: str, boxes, near: tuple | None = None) -> tuple | None:
    """Best OCR box for the named target: exact words beat substrings ("Connect" button over a "…/connectors" URL),
    short labels beat sentences that mention it, and with the pointer on screen the nearest match wins."""
    tg = [norm(x) for x in target.split() if norm(x)]
    if not tg:
        return None
    cands = []
    for text, conf, bb in boxes:
        tx = [norm(x) for x in text.split()]
        joined = "".join(tx)
        hit = sum(1.0 if x in tx else (0.5 if len(x) > 3 and x in joined else 0) for x in tg) / len(tg)
        if hit < 0.5:
            continue
        score = hit - 0.04 * max(0, len(tx) - len(tg)) - 0.004 * max(0, len(text) - len(target) - 3)
        if near:
            cx, cy = bb[0] + bb[2] / 2, bb[1] + bb[3] / 2
            score -= 2.0 * ((cx - near[0]) ** 2 + (cy - near[1]) ** 2) ** 0.5
        cands.append((score, text, bb))
    return max(cands) if cands else None


CURSORS = None


def find_pointer(img: np.ndarray) -> tuple | None:
    """macOS pointer (arrow / hand / text beam, templates in pipeline/tools/cursors) → centre as fractions.
    Trusted only when clearly better than the next-best spot (score ≥ 0.83, margin ≥ 0.035; false hits sat ≤ 0.78 in testing)."""
    global CURSORS
    if CURSORS is None:
        d = Path(__file__).parent / "cursors"
        CURSORS = [(cv2.imread(str(p), 0), (cv2.imread(str(p).replace(".png", "_mask.png"), 0) > 0).astype(np.uint8))
                   for p in sorted(d.glob("*.png")) if not p.name.endswith("_mask.png")]
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    best = None
    for c, m in CURSORS:
        r = np.nan_to_num(cv2.matchTemplate(g, c, cv2.TM_CCOEFF_NORMED, mask=m), nan=-1, posinf=-1, neginf=-1)
        _, mx, _, ml = cv2.minMaxLoc(r)
        r[max(0, ml[1] - 30): ml[1] + 30, max(0, ml[0] - 30): ml[0] + 30] = -1
        cand = (mx, mx - r.max(), (ml[0] + c.shape[1] / 2) / g.shape[1], (ml[1] + c.shape[0] / 2) / g.shape[0])
        if best is None or cand[0] > best[0]:
            best = cand
    return (best[2], best[3]) if best and best[0] >= 0.83 and best[1] >= 0.035 else None


def changed_region(a: np.ndarray, b: np.ndarray) -> tuple | None:
    """Bounding box (fractions) of what changed between two frames, ignoring tiny noise and whole-screen changes."""
    d = cv2.absdiff(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), cv2.cvtColor(b, cv2.COLOR_BGR2GRAY))
    m = (d > 24).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    if n <= 1:
        return None
    H, W = m.shape
    g0 = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float32)
    comps = []
    for s in st[1:]:
        if s[4] < 0.0004 * W * H:
            continue
        x, y, w, h = s[:4]
        if w * h > 0.010 * W * H:  # big blocks are text streaming / scrolling / a page change (real targets are ≤ 0.6%)
            continue
        # something that APPEARS on empty space (a notice, a menu, a new row) beats text that only shifted:
        # weight by how plain that spot was before
        before = float(g0[y:y + h, x:x + w].std())
        comps.append((s[4] / (1 + before / 8), (x / W, y / H, w / W, h / H)))
    return max(comps)[1] if comps else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("project"); ap.add_argument("--from", dest="t0", type=float, default=0)
    ap.add_argument("--to", dest="t1", type=float, default=1e9)
    a = ap.parse_args()
    P = Path("projects") / a.project / "out"
    subprocess.run(["uv", "run", "--project", "pipeline", "python", "pipeline/tools/hybrid_plan.py", a.project],
                   check=True, capture_output=True)
    plan = json.loads((P / "hybrid/plan.json").read_text())
    fps = plan["fps"]
    plain = [(r["cut0"] / fps, r["cut1"] / fps) for r in plan["runs"] if r["kind"] == "ffmpeg"]
    words = json.loads((P / "transcript_cut.json").read_text())["words"]
    layout = json.loads((P / "layout.json").read_text())
    scr = P / "screen_cut.mp4"
    sw, sh = (int(x) for x in subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
              "stream=width,height", "-of", "csv=p=0", str(scr)], capture_output=True, text=True).stdout.strip().split(","))
    # screen fraction → output-frame fraction (object-fit: cover into 1920x1080)
    k = max(1920 / sw, 1080 / sh); ox, oy = (sw * k - 1920) / 2, (sh * k - 1080) / 2
    to_out = lambda x, y: ((x * sw * k - ox) / 1920, (y * sh * k - oy) / 1080)
    card_x = layout.get("card", {}).get("x", 0.7085)

    zooms, log, cands, taken = [], [], [], []
    tmp = Path(tempfile.mkdtemp())
    for tr in triggers(words):
        t = tr["t"]
        if not (a.t0 <= t < a.t1):
            continue
        row = {**tr, "result": ""}
        log.append(row)
        rng = next(((s, e) for s, e in plain if s <= t - 0.3 and t + 1.5 <= e), None)
        if not rng:
            row["result"] = "skip: graphics / full-screen head / image at that moment"; continue
        f0 = frame_at(scr, t, tmp, "f0")
        ptr = find_pointer(f0)
        for dt in (0.3, -0.3, 0.6):  # the pointer may be mid-move on the word's own frame
            if ptr: break
            ptr = find_pointer(frame_at(scr, max(0, t + dt), tmp, "fp"))
        cv2.imwrite(str(tmp / "ocr.png"), f0)
        box, how, mark = None, None, None
        if tr["target"]:
            m = match_text(tr["target"], ocr_boxes(tmp / "ocr.png"), ptr)
            if not m:  # the button may appear a moment later (menu opening)
                f1 = frame_at(scr, t + 0.8, tmp, "f1"); cv2.imwrite(str(tmp / "ocr.png"), f1)
                m = match_text(tr["target"], ocr_boxes(tmp / "ocr.png"), ptr or find_pointer(f1))
            if m:
                box, how, mark = m[2], f"OCR \"{m[1][:40]}\"" + (" near the pointer" if ptr else ""), m[2]
        if box is None and ptr:
            box, how = (ptr[0] - 0.01, ptr[1] - 0.01, 0.02, 0.02), "the mouse pointer"
        if box is None:
            row["result"] = "skip: target not found on screen"; continue
        cx, cy = to_out(box[0] + box[2] / 2, box[1] + box[3] / 2)
        if cx > card_x - 0.02:
            row["result"] = "skip: target under the face card"; continue
        end = min(max(sentence_end(words, tr["i"]), t + 2.5), t + 5, rng[1] - 0.1)
        z = {"from": round(max(rng[0], t - 0.35), 3), "to": round(end, 3), "x": round(cx, 4), "y": round(cy, 4),
             "scale": SCALE, "note": f"auto: \"{tr['say']}\" ({how})"}
        if mark:
            mx, my = to_out(mark[0], mark[1]); mx2, my2 = to_out(mark[0] + mark[2], mark[1] + mark[3])
            z["marks"] = [{"x": round(mx, 4), "y": round(my, 4), "w": round(mx2 - mx, 4), "h": round(my2 - my, 4)}]
        prio = 0 if how.startswith("OCR") else (1 if tr["target"] or tr["verb"] in NAMED else 2)
        cands.append((prio, t, z, row, how, cx, cy))
        row["result"] = "candidate"
    # named buttons found by OCR first, then clicks at the pointer, then "right here"; max one per MIN_GAP
    for prio, t, z, row, how, cx, cy in sorted(cands, key=lambda c: (c[0], c[1])):
        clash = next((zt for zt in taken if abs(zt - t) < MIN_GAP), None)
        if clash is not None:
            row["result"] = f"skip: {abs(t - clash):.1f} s from a stronger zoom (min {MIN_GAP:g})"; continue
        taken.append(t); zooms.append(z)
        row["result"] = f"ZOOM {z['from']:.1f}-{z['to']:.1f}s at ({cx:.2f}, {cy:.2f}) via {how}"
    zooms.sort(key=lambda z: z["from"])
    out = {**layout, "zooms": (layout.get("zooms") or []) + zooms}
    (P / "layout_autozoom.json").write_text(json.dumps(out, indent=1))
    md = [f"# Auto-zooms, {a.project} (cut {a.t0:g}-{min(a.t1, words[-1]['end']):.0f} s)", "",
          f"{len(zooms)} zooms from {len(log)} pointing moments.", "", "| cut time | said | result |", "|---|---|---|"]
    md += [f"| {int(r['t'] // 60)}:{r['t'] % 60:04.1f} | {r['say']} | {r['result']} |" for r in log]
    (P / "autozoom.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
