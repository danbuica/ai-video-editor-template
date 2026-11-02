"""QA pass on the first full cut, before you see it: listen to what the cut ACTUALLY says and flag likely problems.

The cut transcript (transcript_cut.json) comes from the same ASR pass that chose the cuts, so it inherits that
pass's blind spots (swallowed retakes inside stretched words, another language heard as English filler, garbled bits).
Here the finished audio is re-transcribed independently (faster-whisper, no prompt, no context carried over) and:

  diff         heard vs expected words, word by word (expected = what the keep-list kept, NOT the written
               script, so it works on unscripted tutorials/demos too)
  repeat       the same words said twice within a few seconds (leftover retake / backtrack)
  pause        dead air inside the cut
  unclear      runs of low-confidence words
  language     stretches that aren't in the video's language (the one it was transcribed in)
  unheard      sound with speech-level energy that no transcript accounts for (hidden speech or noise)

Outputs (all on the cut timeline = the first full video's timeline):
  out/qa.md        flags, most important first, with context, for the AI review + you
  out/qa.json      the same, machine-readable
  out/qa_heard.md  the heard transcript (timestamped lines, ⏸ for pauses) for the AI's own read-through of
                   unscripted/demo parts, where only judgment can spot problems
"""
from __future__ import annotations

import difflib
from pathlib import Path

import numpy as np

from . import audio, hw
from .common import Project, fmt_time, load_json, norm_token, save_json, ensure_writable

SR = 16000
FILLERS = {"um", "uh", "erm", "hmm", "mm", "ah", "oh"}

SEVERITY = {"high": 0, "medium": 1, "low": 2}
_NUMS = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()
CANON = {**{str(i): w for i, w in enumerate(_NUMS)}, "ok": "okay", "alright": "allright", "gonna": "going", "wanna": "want"}


def _canon(tok: str) -> str:
    return CANON.get(tok, tok)


def _heard(fw, samples: np.ndarray, language: str = "en") -> tuple[list[dict], list[dict]]:
    segs, _ = fw.transcribe(samples, language=language, beam_size=5, word_timestamps=True,
                            condition_on_previous_text=False, vad_filter=True,
                            vad_parameters={"min_silence_duration_ms": 400, "speech_pad_ms": 200})
    words, segments = [], []
    for s in segs:
        if s.no_speech_prob > 0.6 and s.avg_logprob < -1.0:  # likely hallucinated over silence/noise
            continue
        seg = {"start": s.start, "end": s.end, "text": s.text.strip(), "logprob": s.avg_logprob, "words": []}
        for w in s.words or []:
            tok = norm_token(w.word)
            if tok:
                d = {"w": w.word.strip(), "n": tok, "start": float(w.start), "end": float(w.end), "p": float(w.probability)}
                words.append(d)
                seg["words"].append(d)
        segments.append(seg)
    return words, segments


def _ctx(words: list[dict], t0: float, t1: float, pad: float = 3.0) -> str:
    return " ".join(w["w"] for w in words if w["start"] >= t0 - pad and w["end"] <= t1 + pad)


def _flag(flags: list, kind: str, sev: str, t0: float, t1: float, note: str, heard: str = "", expected: str = "") -> None:
    flags.append({"kind": kind, "severity": sev, "t": round(t0, 2), "end": round(t1, 2),
                  "note": note, "heard": heard, "expected": expected})


def _diff(exp: list[dict], heard: list[dict], flags: list) -> None:
    from rapidfuzz import fuzz
    a = [_canon(norm_token(w["w"])) for w in exp]
    b = [_canon(w["n"]) for w in heard]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        ea, hb = a[i1:i2], b[j1:j2]
        if all(t in FILLERS for t in ea + hb):
            continue
        if op == "replace" and fuzz.ratio(" ".join(ea), " ".join(hb)) >= (60 if len(ea) == len(hb) == 1 else 75):
            continue  # spelling/number formatting ("okay"/"ok", "10"/"ten")
        if j2 > j1:
            t0, t1 = heard[j1]["start"], heard[j2 - 1]["end"]
        else:  # expected words that weren't heard: place them between the neighbouring heard words
            t0 = exp[i1]["start"]
            t1 = exp[i2 - 1]["end"]
        n = max(len(ea), len(hb))
        if op == "insert":
            sev = "high" if len(hb) >= 2 else "medium"
            note = "heard words the cut should not contain (leftover attempt, false start, aside?)"
        elif op == "delete":
            sev = "medium" if len(ea) >= 2 else "low"
            note = "expected words not heard (clipped by a cut, mumbled, or the first transcript invented them)"
        else:
            sev = "high" if n >= 3 else "medium"
            note = "the two transcripts disagree here (garbled, another language, or a hidden retake)"
        _flag(flags, "diff", sev, t0, t1, note, heard=" ".join(w["w"] for w in heard[j1:j2]),
              expected=" ".join(w["w"] for w in exp[i1:i2]))


def _repeats(heard: list[dict], flags: list, window: float = 8.0) -> None:
    toks = [w["n"] for w in heard]
    seen_at: set[int] = set()
    for n in (5, 4, 3, 2, 1):
        for i in range(len(toks) - n):
            if i in seen_at:
                continue
            gram = toks[i:i + n]
            if n == 1 and gram[0] in FILLERS:
                continue
            if n <= 2:  # short grams only count when immediately repeated ("it does it does", "the the")
                if toks[i + n:i + 2 * n] != gram:
                    continue
                j = i + n
            else:
                j = next((k for k in range(i + 1, len(toks) - n + 1)
                          if heard[k]["start"] - heard[i]["start"] <= window and toks[k:k + n] == gram), None)
                if j is None:
                    continue
            t0, t1 = heard[i]["start"], heard[j + n - 1]["end"]
            sev = "high" if n >= 3 else ("medium" if n == 2 else "low")
            _flag(flags, "repeat", sev, t0, t1, f"\"{' '.join(gram)}\" said twice in {t1 - t0:.1f}s (leftover retake/backtrack, or deliberate?)",
                  heard=_ctx(heard, t0, t1, 1.5))
            seen_at.update(range(i, j + n))


def _pauses(env: audio.Envelope, heard: list[dict], flags: list, min_gap: float = 0.9) -> list[tuple[float, float]]:
    regions = env.speech_regions()
    gaps = [(a[1], b[0]) for a, b in zip(regions, regions[1:]) if b[0] - a[1] >= min_gap]
    for g0, g1 in gaps:
        sev = "medium" if g1 - g0 >= 1.5 else "low"
        _flag(flags, "pause", sev, g0, g1, f"{g1 - g0:.1f}s of silence inside the cut (fine during a demo action, wrong mid-sentence)",
              heard=f"…{_ctx(heard, g0 - 2, g0, 0)} ⏸ {_ctx(heard, g1, g1 + 2, 0)}…")
    return gaps


def _unheard(env: audio.Envelope, heard: list[dict], exp: list[dict], flags: list) -> None:
    for r0, r1 in env.speech_regions(min_len=0.35):
        if any(w["start"] < r1 + 0.1 and w["end"] > r0 - 0.1 for w in heard):
            continue
        in_exp = [w["w"] for w in exp if w["start"] < r1 and w["end"] > r0]
        _flag(flags, "unheard", "medium" if r1 - r0 >= 0.6 else "low", r0, r1,
              "speech-level sound the re-transcription has no words for (hidden speech? click/breath/noise?)",
              expected=" ".join(in_exp))


def _unclear(heard: list[dict], flags: list, p: float = 0.35) -> list[tuple[float, float]]:
    spans, run = [], []
    for w in heard + [None]:
        if w is not None and w["p"] < p and w["n"] not in FILLERS:
            run.append(w)
            continue
        if len(run) >= 2:
            spans.append((run[0]["start"], run[-1]["end"]))
            _flag(flags, "unclear", "medium", run[0]["start"], run[-1]["end"],
                  "the transcriber is unsure about these words (mumbled, garbled, another language?)",
                  heard=" ".join(x["w"] for x in run))
        run = []
    return spans


def _language(fw, samples: np.ndarray, segments: list[dict], spans: list[tuple[float, float]], flags: list, cap: int = 40,
              language: str = "en") -> None:
    cand = spans + [(s["start"], s["end"]) for s in segments if s["logprob"] < -0.9]
    cand = sorted(set((round(a, 2), round(b, 2)) for a, b in cand))[:cap]
    for a, b in cand:
        clip = samples[int(max(0, a - 0.3) * SR): int((b + 0.3) * SR)]
        if len(clip) < SR * 0.4:
            continue
        segs, info = fw.transcribe(clip, language=None, beam_size=5, condition_on_previous_text=False, vad_filter=False)
        text = " ".join(s.text.strip() for s in segs)
        if info.language != language and info.language_probability >= 0.5:
            _flag(flags, "language", "high", a, b, f"sounds like {info.language} ({info.language_probability:.0%})", heard=text)


def _heard_md(segments: list[dict], gaps: list[tuple[float, float]], dst: Path) -> None:
    ensure_writable(dst)
    lines = ["# What the cut actually says (independent re-transcription)",
             "Cut timeline. ⏸ = pause ≥ 0.9 s. Read it all: flag restarts, self-corrections, unfinished sentences,",
             "off-topic chatter, things said twice, references to something not on screen.", ""]
    gi = 0
    for s in segments:
        while gi < len(gaps) and gaps[gi][0] <= s["start"]:
            lines.append(f"      ⏸ {gaps[gi][1] - gaps[gi][0]:.1f}s")
            gi += 1
        lines.append(f"[{fmt_time(s['start'])}] {s['text']}")
    dst.write_text("\n".join(lines) + "\n")


def qa(project: Project, src: Path | None = None, model_name: str = "large-v3", diff: bool = True) -> dict:
    wav = project.work / "qa_audio.wav"
    audio.extract(Path(src) if src else project.work / "cut_master.wav", wav, SR, mono=True)
    mono, _ = audio.load_mono(wav)
    env = audio.Envelope(audio.envelope_db(mono, SR))
    fw = hw.whisper_model(model_name)
    print(f"[qa] re-transcribing {len(mono) / SR / 60:.1f} min of the cut (~{len(mono) / SR / 2.5 / 60:.0f} min)…", flush=True)
    language = load_json(project.work / "words.json").get("language", "en")  # the language it was transcribed in
    heard, segments = _heard(fw, mono, language)
    exp = load_json(project.out / "transcript_cut.json")["words"] if diff else []

    flags: list[dict] = []
    if diff:
        _diff(exp, heard, flags)
    _repeats(heard, flags)
    gaps = _pauses(env, heard, flags)
    _unheard(env, heard, exp, flags)
    spans = _unclear(heard, flags)
    print("[qa] checking unclear stretches for other languages…", flush=True)
    _language(fw, mono, segments, spans, flags, language=language)
    wav.unlink(missing_ok=True)

    # one entry per spot: merge flags that overlap in time, keep the most severe first
    flags.sort(key=lambda f: f["t"])
    spots: list[dict] = []
    for f in flags:
        if spots and f["t"] <= spots[-1]["end"] + 1.0:
            s = spots[-1]
            s["end"] = max(s["end"], f["end"])
            s["flags"].append(f)
            s["severity"] = min(s["severity"], f["severity"], key=SEVERITY.get)
        else:
            spots.append({"t": f["t"], "end": f["end"], "severity": f["severity"], "flags": [f]})
    report = {"source": str(src or "work/cut_master.wav"), "diffed": diff, "heard_words": len(heard),
              "expected_words": len(exp), "spots": spots}
    save_json(project.out / "qa.json", report)

    md = [f"# QA: {project.name}", "",
          f"{len(spots)} spots ({sum(s['severity'] == 'high' for s in spots)} high, "
          f"{sum(s['severity'] == 'medium' for s in spots)} medium, {sum(s['severity'] == 'low' for s in spots)} low). "
          "Times on the cut timeline. Each spot needs a verdict: fix / fine (why).", ""]
    for sev in ("high", "medium", "low"):
        group = [s for s in spots if s["severity"] == sev]
        if not group:
            continue
        md.append(f"## {sev.upper()} ({len(group)})")
        for s in group:
            md.append(f"- **{fmt_time(s['t'])}–{fmt_time(s['end'])}**")
            for f in s["flags"]:
                md.append(f"  - `{f['kind']}` {f['note']}")
                if f["heard"]:
                    md.append(f"    - heard: \"{f['heard']}\"")
                if f["expected"]:
                    md.append(f"    - expected: \"{f['expected']}\"")
        md.append("")
    ensure_writable(project.out / "qa.md")
    (project.out / "qa.md").write_text("\n".join(md))
    _heard_md(segments, gaps, project.out / "qa_heard.md")
    print(f"[qa] {len(spots)} spots → {project.out / 'qa.md'} · heard transcript → {project.out / 'qa_heard.md'}", flush=True)
    return report
