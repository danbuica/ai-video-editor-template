"""ocr_scan.py <project_dir> [step_s=3] — privacy pass over the KEPT screen: OCR (macOS Vision) a frame every step_s
of the cut, flag emails, inbox/drive lists, account choosers, passwords, codes, API keys; print the moments grouped,
in cut seconds. Deps: uv run --with pyobjc-framework-Vision --with pyobjc-framework-Quartz python … (~15 min / 47 min
video). Writes out/ocr_hits.json. Bare "inbox" is ignored (too common as a folder name)."""
import json, re, subprocess, sys, tempfile
from pathlib import Path
import Vision
from Foundation import NSURL
pdir = Path(sys.argv[1]); STEP = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
e = json.loads((pdir / "out/edl.json").read_text())
pts = []
for s in e["segments"]:
    k = 0.0
    while k < s["src_end_s"] - s["src_start_s"]:
        pts.append((s["out_start_s"] + k, s["src_start_s"] + k)); k += STEP
def ocr(png):
    req = Vision.VNRecognizeTextRequest.alloc().init(); req.setRecognitionLevel_(1)
    Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(png), None).performRequests_error_([req], None)
    return [str(r.topCandidates_(1)[0].string()) for r in (req.results() or [])]
pat = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|primary|promotions|my drive|choose an account|verification code|\bcode\b.*\d{4}|"
                 r"\bsk-[A-Za-z0-9]|ghp_|api key|password|shared with me", re.I)
png = str(Path(tempfile.gettempdir()) / f"ocr_{pdir.name}.png")
hits = []
for i, (o, src) in enumerate(pts):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{src:.2f}", "-i", str(pdir / "work/screen_cfr.mp4"), "-frames:v", "1", png])
    h = [t for t in ocr(png) if pat.search(t)]
    if h: hits.append({"cut": round(o, 2), "src": round(src, 2), "hits": h})
(pdir / "out/ocr_hits.json").write_text(json.dumps(hits, indent=0))
groups = []
for h in hits:
    if groups and h["cut"] - groups[-1]["end"] < 8: groups[-1]["end"] = h["cut"]; groups[-1]["t"].update(x[:50] for x in h["hits"])
    else: groups.append({"start": h["cut"], "end": h["cut"], "src": h["src"], "t": set(x[:50] for x in h["hits"])})
for g in groups:
    print(f"cut {g['start']:.0f}-{g['end']:.0f}s (src {g['src']:.0f}): " + " | ".join(sorted(g["t"]))[:240])
