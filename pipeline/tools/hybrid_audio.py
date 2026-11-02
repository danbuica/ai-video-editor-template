"""Fast 4K final: Final's soundtrack mixed in numpy instead of by Remotion (which walks every frame just to make sound).

Replicates Final.tsx + Main.tsx exactly: the voice (talking_cut audio) per chapter segment, the chapterSfx on every chapter
card, every SFX event of the motion plan (Main's SfxTrack, clipped to its segment), and the music bed with
Final.tsx's musicGain (look-ahead ducking under speech, louder on cards, fade in/out), volume held per video frame.

  uv run --project pipeline python pipeline/tools/hybrid_audio.py <name> [--check <remotion pcm .mov>]
→ projects/<name>/out/hybrid/audio.wav (48 kHz stereo float); --check nulls it against a Remotion render."""
from __future__ import annotations

import argparse, json, math, subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 48000
jsround = lambda x: math.floor(x + 0.5)


def decode(p: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-map", "0:a:0", "-ac", "2", "-ar", str(SR),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).copy()


def interp(x: float, a: float, b: float, ya: float, yb: float) -> float:
    """Remotion interpolate() with both sides clamped."""
    if x <= a: return ya
    if x >= b: return yb
    return ya + (yb - ya) * (x - a) / (b - a)


def music_gain(t: float, total: float, speech, cards, lufs: float, gain_db: float, fade_in=True, fade_out=True) -> float:
    db = lambda x: 10 ** (x / 20)
    norm = db(-20 - lufs + gain_db)
    if any(t >= a - 0.1 and t <= b + 0.1 for a, b in cards):
        return norm * db(-12)
    duck = 0.0
    for a, b in speech:
        if t >= a - 0.15 and t <= b:
            duck = 1.0; break
        if t < a - 0.15:
            duck = max(duck, interp(a - t, 0.15, 0.45, 1, 0)); break
        if t > b:
            duck = max(duck, interp(t - b, 0, 0.6, 1, 0))
    level = -17 + (-22 - -17) * duck
    fade_in = min(1.0, t / 1.5) if fade_in else 1.0  # interpolate(t, [0, 1.5], [0, 1], clamp right) (t ≥ 0)
    fade_out = interp(t, total - 3, total, 1, 0) if fade_out else 1.0
    return norm * db(level) * fade_in * fade_out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("project"); ap.add_argument("--motion", default="motion.json"); ap.add_argument("--check")
    ap.add_argument("--out", default="", help="default out/hybrid/audio.wav")
    ap.add_argument("--music-from", type=float, default=0.0, help="part of a long video: start this far into the bed (s)")
    ap.add_argument("--no-fade-in", action="store_true"); ap.add_argument("--no-fade-out", action="store_true")
    ap.add_argument("--card-after", action="store_true", help="part: the next part opens on a chapter card")
    ap.add_argument("--smooth-music", action="store_true", help="exact ducking curve instead of Remotion's 1/97 steps")
    ap.add_argument("--block", type=int, default=4096, help="samples per volume evaluation (ffmpeg audio frame)")
    a = ap.parse_args()
    root = Path("projects")
    P = root / a.project / "out"
    edl = json.loads((P / "edl.json").read_text())
    plan = json.loads((P / a.motion).read_text())
    words = json.loads((P / "transcript_cut.json").read_text())["words"]
    lib_file = root / "_assets/sfx/library.json"
    lib = json.loads(lib_file.read_text()) if lib_file.exists() else {}
    fps = edl["fps_float"]; spf = round(SR / fps); total_cut = edl["out_frames"]
    by_src = {w["src_i"]: w for w in words}

    def tref(r):
        if isinstance(r, (int, float)): return float(r)
        w = by_src.get(r["w"]) or next((x for x in words if x["src_i"] > r["w"]), words[-1])
        return (w["end"] if r.get("end") else w["start"]) + r.get("pad", 0)

    card_frames = jsround(plan.get("chapterSeconds", 2) * fps)
    chapters = sorted(jsround(tref(c["at"]) * fps) for c in plan.get("chapters", []))
    bounds = [0] + chapters + [total_cut]
    segs = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]
    total = total_cut + len(chapters) * card_frames
    out = np.zeros((total * spf, 2), np.float32)
    comps = {}
    snap = lambda k: comps.__setitem__(k, out.copy() - sum(comps.values(), np.zeros_like(out)))

    # voice: each segment plays the cut's own audio
    voice = decode(P / "talking_cut.mp4")
    seg_final0 = []
    for i, (s, e) in enumerate(segs):
        f0 = s + i * card_frames; seg_final0.append(f0)
        src = voice[s * spf: e * spf]
        out[f0 * spf: f0 * spf + len(src)] += src
    snap('voice')

    # chapter cards: the plan's chapterSfx from 0.6 s in, for the card's length, volume sfxBase * 0.9
    sfx_base_final = plan.get("sfxVolume", 0.125)
    if plan.get("chapterSfx"):
        wh = decode(root / f"_assets/sfx/{plan['chapterSfx']}.wav")[jsround(0.6 * fps) * spf:][: card_frames * spf]
        for i in range(1, len(segs)):
            c0 = (seg_final0[i] - card_frames) * spf
            out[c0: c0 + len(wh)] += wh * sfx_base_final * 0.9
    snap('cards')

    # SFX events (Main's SfxTrack), each Main instance clipped to its segment
    base = plan.get("sfxVolume", 0.22)
    cache: dict[str, np.ndarray] = {}
    for it in plan.get("items", []):
        for ev in it.get("sfx", []):
            L = lib.get(ev["name"])
            if not L: continue
            x = cache.setdefault(ev["name"], decode(root / L["file"]))
            start = tref(ev["at"]) - (L["peak_at"] if ev.get("hit") else 0)
            fr = jsround(start * fps)
            x = x[: (math.ceil(L["duration"] * fps) + 2) * spf] * (base * ev.get("vol", 1) * 10 ** (L.get("trim_db", 0) / 20))
            for i, (s, e) in enumerate(segs):
                a0, a1 = max(fr * spf, s * spf), min(fr * spf + len(x), e * spf)
                if a1 <= a0: continue
                d0 = (seg_final0[i] - s) * spf + a0
                out[d0: d0 + (a1 - a0)] += x[a0 - fr * spf: a1 - fr * spf]
    snap('sfx')

    # music bed with Final's ducking, gain held per frame
    m = plan.get("music")
    if m:
        shift = lambda cs: cs + sum(1 for c in chapters if c <= cs * fps + 0.5) * card_frames / fps
        speech = []
        for w in words:
            s_, e_ = shift(w["start"]), shift(w["end"])
            if speech and s_ - speech[-1][1] < 0.45: speech[-1][1] = e_
            else: speech.append([s_, e_])
        cards = [((c + i * card_frames) / fps, (c + i * card_frames) / fps + card_frames / fps) for i, c in enumerate(chapters)]
        if a.card_after:  # Final.tsx's cardAfter: the next part's opening card
            cards.append((total / fps, (total + card_frames) / fps))
        mus = decode(root / m["file"])[jsround(a.music_from * fps) * spf:][: total * spf]  # Audio startFrom (frames)
        g = np.array([music_gain(F / fps, total / fps, speech, cards, m["lufs"], m.get("gainDb", 0),
                                 not a.no_fade_in, not a.no_fade_out) for F in range(total)])
        if a.smooth_music:  # what Final.tsx asks for: the exact gain, held per frame
            gs = np.repeat(g, spf)[: len(mus)]
        else:  # what Remotion actually plays (renderer/assets/ffmpeg-volume-expression.js): each frame's volume rounded
            # to 1/97 steps (3 decimals), frame f's value used for t in [(f-0.5)/fps, (f+0.5)/fps], evaluated once per
            # audio block (volume=...:eval=frame)
            q = np.array([float(f"{math.floor(v * 97 + 0.5) / 97:.3f}") for v in g] + [0.0])
            blk = np.arange(len(mus)) // a.block * a.block
            gs = q[np.minimum(np.floor(blk / SR * fps + 0.5).astype(int), len(q) - 1)]
        out[: len(mus)] += mus * gs[:, None].astype(np.float32)
    snap('music')

    dst = Path(a.out) if a.out else P / "hybrid" / "audio.wav"; dst.parent.mkdir(exist_ok=True)
    sf.write(str(dst), out, SR, subtype="FLOAT")
    print(f"[audio] {total} frames, {len(out) / SR:.2f} s, peak {20 * np.log10(np.abs(out).max() + 1e-12):.1f} dBFS → {dst}")

    if a.check:
        ref = decode(Path(a.check))
        n = min(len(ref), len(out))
        r, o = ref[:n].mean(1), out[:n].mean(1)
        res = 10 * np.log10(np.mean((r - o) ** 2) / np.mean(r ** 2))
        print(f"[audio] null vs {a.check}: {res:.1f} dB over {n / SR:.1f} s")
        w = 10 * SR
        worst = sorted(((10 * np.log10(np.mean((r[i:i + w] - o[i:i + w]) ** 2) / max(np.mean(r[i:i + w] ** 2), 1e-12)), i / SR)
                        for i in range(0, n - w, w)), reverse=True)[:6]
        M = np.stack([c[:n].mean(1) for c in comps.values()], 1)
        coef, *_ = np.linalg.lstsq(M[::7], r[::7], rcond=None)
        print("[audio] best-fit gain per part:", {k: round(float(c), 4) for k, c in zip(comps, coef)},
              "residual after fit:", round(float(10 * np.log10(np.mean((r - M @ coef) ** 2) / np.mean(r ** 2))), 1), "dB")
        for k, c in comps.items():  # residual with this part removed from both sides (rough share)
            pk = c[:n].mean(1); print(f"   {k:6} level {10 * np.log10(np.mean(pk ** 2) / np.mean(r ** 2)):6.1f} dB")
        print("[audio] worst 10 s windows:", ", ".join(f"{t:.0f}s {d:.1f} dB" for d, t in worst))


if __name__ == "__main__":
    main()
