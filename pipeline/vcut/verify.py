"""Stage 7: prove the two outputs are frame-identical in length, synced, and joined in silence."""
from __future__ import annotations

import json

import numpy as np

from . import audio
from .common import Project, fmt_time, load_json, run, save_json


def count_frames(path) -> int:
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
               "-show_entries", "stream=nb_read_packets", "-of", "json", str(path)])
    return int(json.loads(out)["streams"][0]["nb_read_packets"])


def verify(project: Project, asr: bool = False) -> dict:
    edl = load_json(project.out / "edl.json")
    talking = project.out / "talking_cut.mp4"
    screen = project.out / "screen_cut.mp4"
    report: dict = {"ok": True, "checks": []}

    def check(name: str, ok: bool, detail: str) -> None:
        report["checks"].append({"check": name, "ok": ok, "detail": detail})
        if not ok:
            report["ok"] = False
        print(f"  {'✅' if ok else '❌'} {name}: {detail}", flush=True)

    print("[verify]", flush=True)
    ft, fs = count_frames(talking), count_frames(screen)
    check("frame count", ft == fs == edl["out_frames"],
          f"talking {ft}, screen {fs}, expected {edl['out_frames']}")

    # Joins land in silence (measured on the cut master audio)
    a, sr = audio.load_mono(project.work / "cut_master.wav")
    env = audio.Envelope(audio.envelope_db(a, sr))
    dur_a = len(a) / sr
    check("audio length", abs(dur_a - edl["out_s"]) < 0.02, f"{dur_a:.3f}s vs video {edl['out_s']:.3f}s")
    # Every kept word made it into the cut. A word whose alignment is glued to a cut attempt
    # ("a— a", "wait. And") can be swallowed by a tight join: fix its start in words.json.
    kept = {w["src_i"] for w in load_json(project.out / "transcript_cut.json")["words"]}
    decisions = load_json(project.work / "decisions.json")
    if decisions.get("_keeps"):
        from .transcribe import load_words
        words = load_words(project)
        lost = [k for a_, b_, _ in decisions["_keeps"] for k in range(a_, b_ + 1) if k not in kept]
        check("kept words present", not lost,
              f"all {len(kept)} kept words are in the cut" if not lost else
              "missing: " + ", ".join(f"{k} '{words[k]['w']}' ({words[k]['start']:.2f}s)" for k in lost[:12]))

    inner = [j for j in edl["joins"] if j["kind"] not in ("head", "tail")]
    # "speech" = near speech level (within 12 dB of the speech peaks); clicks/breaths at a join are fine
    speech_lvl = max(env.thr + 8, env.peak - 12)

    def loud_at(t: float) -> bool:
        a_, b_ = env.i(t - 0.008), env.i(t + 0.008) + 1
        return bool(np.any(env.db[a_:b_] >= speech_lvl))
    loud = [j for j in inner if not j.get("tight") and loud_at(j["out_s"])]
    check("joins in silence", not loud,
          f"{len(inner) - len([j for j in inner if j.get('tight')])} joins fall in silence" if not loud else
          "speech at: " + ", ".join(f"{fmt_time(j['out_s'])} ({j.get('text_before', '')[-25:]} ‖ {j.get('text_after', '')[:25]})" for j in loud[:12]))
    tight = [j for j in inner if j.get("tight")]
    if tight:
        # tight joins cut between two words with no pause: report how quiet the cut point is
        # level at the cut = quietest point within ±10 ms (the audio may sit up to ½ frame off the video edge)
        levels = [float(env.db[env.i(j["out_s"] - 0.01):env.i(j["out_s"] + 0.01) + 1].min() - env.floor) for j in tight]
        report["tight_joins"] = [{"out_s": j["out_s"], "db_over_floor": round(l, 1),
                                  "text": f"{j.get('text_before', '')} ‖ {j.get('text_after', '')}"}
                                 for j, l in zip(tight, levels)]
        speech_range = env.peak - env.floor
        bad = [r for r in report["tight_joins"] if r["db_over_floor"] > 0.6 * speech_range]
        check("tight joins at a quiet point", not bad,
              f"{len(tight)} tight joins, loudest cut point {max(levels):.0f} dB over room tone "
              f"(speech peaks ~{speech_range:.0f} dB over)" + ("" if not bad else f"; LOUD: {bad}"))

    # Sync between the two cut files (needs the screen recording's own audio)
    if (project.work / "cut_screen.wav").exists():
        b, _ = audio.load_mono(project.work / "cut_screen.wav")
        a16 = a[::3]  # 48k → 16k is enough for an offset check
        b16 = b[::3]
        res = audio.sync_check(a16, b16, sr // 3)
        good = [r for r in res if r["strength"] > 0.05]
        frame_ms = 1000 / edl["fps_float"]
        ok = all(abs(r["offset_ms"]) <= frame_ms for r in good) if good else True
        check("A/V sync between files", ok,
              (f"offsets {[r['offset_ms'] for r in good]} ms (limit ±{frame_ms:.0f})" if good else "too weak to measure"))
        # And measured from the rendered mp4s themselves (catches muxing/encoder offsets)
        tmp_a, tmp_b = project.work / "_vt.wav", project.work / "_vs.wav"
        audio.extract(talking, tmp_a, 16000, mono=True)
        audio.extract(screen, tmp_b, 16000, mono=True)
        ra, _ = audio.load_mono(tmp_a)
        rb, _ = audio.load_mono(tmp_b)
        res2 = [r for r in audio.sync_check(ra, rb, 16000) if r["strength"] > 0.05]
        if res2:
            check("rendered files in sync", all(abs(r["offset_ms"]) <= frame_ms for r in res2),
                  f"offsets {[r['offset_ms'] for r in res2]} ms")
        tmp_a.unlink(missing_ok=True)
        tmp_b.unlink(missing_ok=True)

    if asr:
        report["asr"] = asr_check(project, edl)
        check("re-transcription matches", report["asr"]["similarity"] >= 90,
              f"{report['asr']['similarity']:.1f}% similar to the expected script")

    save_json(project.out / "verify.json", report)
    return report


def asr_check(project: Project, edl: dict) -> dict:
    """Re-transcribe the cut and compare with the script we intended to keep."""
    import whisperx
    from rapidfuzz import fuzz

    from .common import norm_token

    expected = [norm_token(w["w"]) for w in load_json(project.out / "transcript_cut.json")["words"]]
    a, sr = audio.load_mono(project.work / "cut_master.wav")
    a16 = np.interp(np.arange(0, len(a), 3), np.arange(len(a)), a).astype(np.float32)
    model = whisperx.load_model("large-v3", "cpu", compute_type="int8", language="en")
    res = model.transcribe(a16, batch_size=8, language="en")
    got = [norm_token(w) for s in res["segments"] for w in s["text"].split()]
    exp_s, got_s = " ".join(t for t in expected if t), " ".join(t for t in got if t)
    return {"similarity": fuzz.ratio(exp_s, got_s), "expected": exp_s, "got": got_s}
