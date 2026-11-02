"""Text on a screenshot, with where it is: macOS Vision on a Mac, RapidOCR (ONNX, CPU) everywhere else.
Used by pipeline/tools/autozoom.py (find "Connect" on screen) and pipeline/tools/ocr_scan.py (privacy pass).

Deps come with the tools' `uv run --with …` line:
  macOS:   --with pyobjc-framework-Vision --with pyobjc-framework-Quartz
  others:  --with rapidocr-onnxruntime
"""
from __future__ import annotations

import sys
from pathlib import Path

_rapid = None


def read(png: Path | str, fast: bool = False) -> list[tuple[str, float, tuple[float, float, float, float]]]:
    """(text, confidence, (x, y, w, h) as fractions of the image, origin top-left), one per line of text.
    On a Mac, fast = Vision's fast mode with language correction (the privacy scan over a whole video); the default is
    its accurate mode without correction (autozoom: exact button labels). RapidOCR has one mode."""
    if sys.platform == "darwin":
        try:
            return _vision(Path(png), fast)
        except ImportError:
            pass
    return _rapidocr(Path(png))


def _vision(png: Path, fast: bool):
    import Vision
    from Foundation import NSURL
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(1 if fast else 0)  # 0 = accurate, 1 = fast
    if not fast:
        req.setUsesLanguageCorrection_(False)
    Vision.VNImageRequestHandler.alloc().initWithURL_options_(NSURL.fileURLWithPath_(str(png)), None).performRequests_error_([req], None)
    res = []
    for r in req.results() or []:
        c = r.topCandidates_(1)[0]
        bb = r.boundingBox()
        res.append((str(c.string()), float(c.confidence()),
                    (bb.origin.x, 1 - bb.origin.y - bb.size.height, bb.size.width, bb.size.height)))
    return res


def _rapidocr(png: Path):
    global _rapid
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        raise SystemExit("OCR needs RapidOCR here: run the tool with `uv run --project pipeline --with rapidocr-onnxruntime …`")
    import cv2
    if _rapid is None:
        _rapid = RapidOCR()
    img = cv2.imread(str(png))
    H, W = img.shape[:2]
    found, _ = _rapid(img)
    res = []
    for box, text, conf in found or []:
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        res.append((text, float(conf), (min(xs) / W, min(ys) / H, (max(xs) - min(xs)) / W, (max(ys) - min(ys)) / H)))
    return res
