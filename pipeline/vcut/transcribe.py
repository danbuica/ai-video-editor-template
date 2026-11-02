"""Stage 2: verbatim-ish transcription with word-level timing (WhisperX), plus a recovery pass
for speech Whisper silently dropped (typically the failed half of a retake)."""
from __future__ import annotations

import logging
import os
import time
import warnings

import numpy as np

from . import audio
from .common import Project, fmt_time, load_json, save_json

warnings.filterwarnings("ignore")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Priming Whisper with disfluent text makes it keep false starts and fillers instead of "cleaning" them.
DISFLUENT_PROMPT = (
    "Um, so, uh, this is the— this is the map. I mean, like, the, the main thing is— okay, wait. "
    "Let me say that again. So this is the map of, uh, every agent I use."
)
# Names said in this video, appended to the prompt so Whisper spells them ("Claude", not "Cloud"/"Claw"/"Cloth"):
# projects/<name>/names.txt (comma or line separated, from the script's tools/products), else these (your channel's
# usual names: set them when you customize the editor).
DEFAULT_NAMES = ""
# Recovery pass on the Apple GPU (mlx-whisper, large-v3): ~8× faster than faster-whisper on CPU and as clean.
# Falls back to faster-whisper on CPU when mlx-whisper isn't installed.
MLX_REPO = "mlx-community/whisper-large-v3-mlx"


def names_prompt(project: Project) -> str:
    f = project.dir / "names.txt"
    raw = f.read_text() if f.exists() else DEFAULT_NAMES
    names = ", ".join(x.strip() for x in raw.replace("\n", ",").split(",") if x.strip())
    return DISFLUENT_PROMPT + (f" Today: {names}." if names else "")


def align_device() -> str:
    """wav2vec2 alignment on the Apple GPU (MPS) when there is one: same model, same times, ~2.5× faster."""
    try:
        import torch
        return "mps" if torch.backends.mps.is_available() else "cpu"
    except Exception:
        return "cpu"


def _mlx_text(clip: np.ndarray, language: str = "en") -> str:
    import mlx_whisper
    r = mlx_whisper.transcribe(clip.astype(np.float32), path_or_hf_repo=MLX_REPO, language=language,
                               condition_on_previous_text=False, no_speech_threshold=0.4, verbose=None)
    return " ".join(s["text"].strip() for s in r["segments"]).strip()


def _fill_missing_times(words: list[dict]) -> None:
    """Some tokens (numbers, symbols) come back from alignment without times: interpolate them."""
    n = len(words)
    for k, w in enumerate(words):
        if w.get("start") is None or w.get("end") is None:
            prev_end = next((words[j]["end"] for j in range(k - 1, -1, -1) if words[j].get("end") is not None), None)
            nxt_start = next((words[j]["start"] for j in range(k + 1, n) if words[j].get("start") is not None), None)
            if prev_end is None and nxt_start is None:
                continue
            if prev_end is None:
                prev_end = max(0.0, nxt_start - 0.3)
            if nxt_start is None:
                nxt_start = prev_end + 0.3
            w["start"] = prev_end
            w["end"] = max(prev_end + 0.05, nxt_start)
            w["score"] = 0.0
            w["interpolated"] = True


def _flatten(aligned: dict, seg_offset: int = 0) -> list[dict]:
    words = []
    for si, seg in enumerate(aligned["segments"]):
        for w in seg.get("words", []):
            text = (w.get("word") or "").strip()
            if not text:
                continue
            words.append({
                "w": text,
                "start": w.get("start"),
                "end": w.get("end"),
                "score": round(float(w.get("score", 0) or 0), 3),
                "seg": si + seg_offset,
            })
    return words


def transcribe(project: Project, model_name: str = "large-v3", language: str = "en",
               chunk_size: int = 15, batch_size: int = 8, threads: int | None = None) -> dict:
    import whisperx
    from faster_whisper import WhisperModel

    logging.getLogger("whisperx").setLevel(logging.WARNING)
    threads = threads or max(4, (os.cpu_count() or 8) - 2)
    t0 = time.time()

    wav16 = project.work / "asr16k.wav"
    if not wav16.exists():
        raise SystemExit("Run `vcut probe` first.")
    samples, sr = audio.load_mono(wav16)
    assert sr == 16000

    print(f"[transcribe] loading {model_name} (CPU int8, {threads} threads)…", flush=True)
    model = whisperx.load_model(
        model_name, "cpu", compute_type="int8", language=language, threads=threads,
        asr_options={"initial_prompt": names_prompt(project), "condition_on_previous_text": False,
                     "no_speech_threshold": 0.4},
        vad_options={"vad_onset": 0.4, "vad_offset": 0.3},
    )
    print(f"[transcribe] transcribing {fmt_time(len(samples) / sr)} of audio…", flush=True)
    result = model.transcribe(samples, batch_size=batch_size, chunk_size=chunk_size, language=language)
    print(f"[transcribe] ASR done in {time.time() - t0:.0f}s, aligning words…", flush=True)

    dev = align_device()
    align_model, meta = whisperx.load_align_model(language_code=language, device=dev)
    aligned = whisperx.align(result["segments"], align_model, meta, samples, dev)
    words = _flatten(aligned)
    _fill_missing_times(words)
    words = [w for w in words if w.get("start") is not None]

    save_json(project.work / "words_main.json", {"words": words})
    words, recovered = recover(words, samples, sr, model.model, align_model, meta, language, dev)
    for i, w in enumerate(words):
        w["i"] = i
        w["start"] = round(float(w["start"]), 3)
        w["end"] = round(float(w["end"]), 3)
    env = audio.Envelope(audio.envelope_db(samples, sr))

    out = {
        "model": model_name,
        "language": language,
        "duration": len(samples) / sr,
        "elapsed_s": round(time.time() - t0, 1),
        "recovered_words": recovered,
        "words": words,
    }
    save_json(project.work / "words.json", out)
    np.save(project.work / "envelope.npy", env.db)
    print(f"[transcribe] {len(words)} words ({recovered} recovered) in {out['elapsed_s']}s", flush=True)
    return out


HALLUCINATIONS = {"thank you", "thanks for watching", "thank you for watching", "here we go", "you", "bye",
                  "so this is the map of uh", "so this is the map of", "i mean like", "okay wait",
                  "subtitles by the amaraorg community"}


def clean_recovered(words: list[dict]) -> tuple[list[dict], int]:
    """Recovered (2nd-pass) words are only trusted where the first pass had nothing:
    drop ones overlapping first-pass words, and whole recovered segments that are classic
    Whisper hallucinations on noise ("Thank you.", "Here we go.") or echoes of the priming text."""
    from .common import norm_token

    main = [w for w in words if not w.get("recovered")]
    rec = [w for w in words if w.get("recovered")]
    keep_rec = []
    for w in rec:
        dur = max(w["end"] - w["start"], 0.02)
        ov = sum(max(0.0, min(w["end"], m["end"]) - max(w["start"], m["start"])) for m in main
                 if m["end"] > w["start"] and m["start"] < w["end"])
        if ov / dur <= 0.3:
            keep_rec.append(w)
    segs: dict[int, list[dict]] = {}
    for w in keep_rec:
        segs.setdefault(w["seg"], []).append(w)
    prompt_toks = [norm_token(t) for t in DISFLUENT_PROMPT.split()]
    phrases = [h.split() for h in HALLUCINATIONS]
    out = list(main)
    for seg in segs.values():
        toks = [norm_token(w["w"]) for w in seg]
        drop = [False] * len(seg)
        for ph in phrases:  # strip known hallucinated phrases wherever they occur in the segment
            n = len(ph)
            for i in range(len(toks) - n + 1):
                if toks[i:i + n] == ph:
                    drop[i:i + n] = [True] * n
        for i in range(len(toks) - 3):  # 4+ word echo of the priming prompt
            for j in range(len(prompt_toks) - 3):
                if toks[i:i + 4] == prompt_toks[j:j + 4]:
                    drop[i:i + 4] = [True] * 4
        out.extend(w for w, d in zip(seg, drop) if not d)
    out.sort(key=lambda w: (w["start"], w["end"]))
    return out, len(words) - len(out)


def recover(words: list[dict], samples, sr: int, fw, align_model, meta, language: str,
            dev: str = "cpu") -> tuple[list[dict], int]:
    """Recovery pass: loud regions with no words = speech Whisper skipped (often the failed half of
    a retake). Re-transcribe just that slice, with NO priming prompt (it leaks into short clips)."""
    import whisperx
    from faster_whisper import WhisperModel

    words = [w for w in words if not w.get("recovered")]
    env = audio.Envelope(audio.envelope_db(samples, sr))
    gaps = []
    for r0, r1 in env.speech_regions(min_len=0.3):
        covered = sum(max(0.0, min(r1, w["end"]) - max(r0, w["start"])) for w in words
                      if w["end"] > r0 and w["start"] < r1)
        if covered / (r1 - r0) < 0.3:
            gaps.append((r0, r1))
    if not gaps:
        return words, 0
    try:
        import mlx_whisper  # noqa: F401
        engine = "mlx"
    except ImportError:
        engine = "cpu"
    print(f"[transcribe] {len(gaps)} speech regions had no words, re-transcribing them ({engine})…", flush=True)
    found = []
    for g, (r0, r1) in enumerate(gaps):
        a = max(0.0, r0 - 0.2)
        b = min(len(samples) / sr, r1 + 0.2)
        clip = samples[int(a * sr): int(b * sr)]
        if engine == "mlx":
            text = _mlx_text(clip, language)
        else:
            segs, _ = WhisperModel.transcribe(fw, clip, language=language, beam_size=5,
                                              condition_on_previous_text=False, vad_filter=False)
            text = " ".join(s.text.strip() for s in segs).strip()
        if not text:
            continue
        al = whisperx.align([{"text": text, "start": a, "end": b}], align_model, meta, samples, dev)
        new = _flatten(al, seg_offset=10_000 + g)  # one segment id per recovered region
        _fill_missing_times(new)
        for w in new:
            if w.get("start") is not None:
                w["recovered"] = True
                found.append(w)
    merged, dropped = clean_recovered(words + found)
    kept = len(found) - dropped
    print(f"[transcribe] recovered {kept} words ({dropped} dropped as duplicates/hallucinations)", flush=True)
    return merged, kept


def recover_only(project: Project, model_name: str = "large-v3", language: str = "en") -> dict:
    """Re-run just the recovery pass on top of the saved first-pass words."""
    import whisperx
    from faster_whisper import WhisperModel

    from .common import load_json
    src = project.work / "words_main.json"
    if not src.exists():
        raise SystemExit("No words_main.json: run a full `vcut transcribe` first.")
    words = load_json(src)["words"]
    samples, sr = audio.load_mono(project.work / "asr16k.wav")
    fw = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=max(4, (os.cpu_count() or 8) - 2))
    dev = align_device()
    align_model, meta = whisperx.load_align_model(language_code=language, device=dev)
    words, recovered = recover(words, samples, sr, fw, align_model, meta, language, dev)
    for i, w in enumerate(words):
        w["i"] = i
        w["start"] = round(float(w["start"]), 3)
        w["end"] = round(float(w["end"]), 3)
    out = load_json(project.work / "words.json")
    out.update({"words": words, "recovered_words": recovered})
    save_json(project.work / "words.json", out)
    return out


def load_words(project: Project) -> list[dict]:
    return load_json(project.work / "words.json")["words"]
