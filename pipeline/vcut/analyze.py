"""Stage 3+4: group words into phrases, classify pauses, and propose retake cuts.

The algorithm aims for high recall with readable evidence. Claude reviews `candidates.md`
and edits `decisions.json` (the "decide" step) before the EDL is built.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from .common import Project, fmt_time, load_json, norm_token, save_json
from .transcribe import load_words

PHRASE_GAP = 0.35          # a pause this long starts a new phrase
REPORT_GAP = 0.25          # pauses shorter than this are never touched
RESTART_WINDOW_S = 75.0    # how far ahead a restart of the same sentence can appear
RESTART_WINDOW_PHRASES = 16

FILLERS = {"um", "uh", "uhm", "umm", "erm", "er", "ah", "eh", "hmm", "mm", "mhm"}
STOP = {
    "the", "a", "an", "and", "or", "but", "so", "to", "of", "in", "on", "at", "for", "with", "is", "it", "this",
    "that", "i", "you", "we", "they", "he", "she", "my", "your", "our", "be", "are", "was", "were", "do", "if",
    "as", "by", "from", "just", "like", "okay", "ok", "now", "then", "here", "there", "what", "how", "can", "will",
    "it's", "i'm", "you're", "we're", "that's", "there's", "let's", "gonna", "really", "very", "all", "um", "uh",
}
STUTTER_OK = {"the", "a", "an", "i", "to", "and", "so", "we", "it", "is", "this", "in", "of", "you", "my", "it's", "i'm"}
STRONG_MARKERS = [
    r"\blet me (?:redo|re-do|repeat|start|say|try|do) (?:that|this|it)?\s*(?:again|over)?",
    r"\bstart (?:that )?over\b", r"\bone more time\b", r"\bscratch that\b", r"\btake two\b",
    r"\bsay (?:that|it) again\b", r"\bfrom the (?:top|beginning)\b", r"\bno,? no\b", r"\bdamn\b", r"\bfuck\b",
    r"\bshit\b", r"\bcut\b", r"\bagain\b", r"\bwait\b", r"\bsorry\b", r"\bhold on\b", r"\bactually,? no\b",
]
WEAK_MARKERS = {"okay", "ok", "alright", "all right", "right", "so", "yeah", "no"}


@dataclass
class Phrase:
    id: int
    w0: int
    w1: int  # inclusive
    start: float
    end: float
    text: str
    toks: list[str]
    ends_sentence: bool
    gap_before: float
    gap_after: float = 0.0


@dataclass
class Candidate:
    words: tuple[int, int]  # inclusive range to cut
    type: str
    confidence: float
    reason: str
    accept: bool
    keeper: int | None = None  # first word of the take that replaces this one
    id: str = ""
    extra: dict = field(default_factory=dict)


def punct_class(word: str) -> str:
    w = word.rstrip("\"')]}”’")
    if w.endswith((".", "?", "!", "…")):
        return "sentence"
    if w.endswith((",", ";", ":", "—", "–", "-")):
        return "comma"
    return "mid"


def natural_gap(words: list[dict]) -> float:
    gaps = [words[k + 1]["start"] - words[k]["end"] for k in range(len(words) - 1)]
    fluent = [g for g in gaps if 0.02 < g < 0.3]
    if len(fluent) < 10:
        return 0.10
    return round(min(0.16, max(0.07, statistics.median(fluent))), 3)


def build_phrases(words: list[dict]) -> list[Phrase]:
    phrases: list[Phrase] = []
    start = 0
    for k in range(len(words)):
        last = k == len(words) - 1
        gap = 0.0 if last else words[k + 1]["start"] - words[k]["end"]
        if last or gap >= PHRASE_GAP or punct_class(words[k]["w"]) == "sentence":
            ws = words[start:k + 1]
            toks = [norm_token(w["w"]) for w in ws]
            phrases.append(Phrase(
                id=len(phrases) + 1, w0=start, w1=k, start=ws[0]["start"], end=ws[-1]["end"],
                text=" ".join(w["w"] for w in ws), toks=toks,
                ends_sentence=punct_class(ws[-1]["w"]) == "sentence",
                gap_before=0.0 if start == 0 else round(ws[0]["start"] - words[start - 1]["end"], 3),
                gap_after=round(gap, 3),
            ))
            start = k + 1
    return phrases


def _content(toks: list[str]) -> list[str]:
    return [t for t in toks if t and t not in FILLERS]


def _prefix_match(a: list[str], b: list[str]) -> int:
    """Number of leading tokens of a and b that match (exactly or near-exactly)."""
    m = 0
    for x, y in zip(a, b):
        if x == y or (len(x) > 3 and fuzz.ratio(x, y) >= 85):
            m += 1
        else:
            break
    return m


def detect_restarts(phrases: list[Phrase]) -> list[Candidate]:
    """Phrase i is a failed take if a later phrase j (close by) starts the same way or repeats it."""
    cands = []
    for pi, p in enumerate(phrases):
        a = _content(p.toks)
        if len(a) < 2:
            continue
        for q in phrases[pi + 1: pi + 1 + RESTART_WINDOW_PHRASES]:
            if q.start - p.end > RESTART_WINDOW_S:
                break
            b = _content(q.toks)
            if len(b) < 2:
                continue
            m = _prefix_match(a, b)
            has_content = any(t not in STOP for t in a[:m])
            truncated_copy = len(a) <= len(b) and m >= 2 and m >= len(a) - 1
            prefix_hit = (m >= 3 and has_content) or (m >= 4) or (truncated_copy and has_content)
            whole_hit = len(a) >= 4 and fuzz.ratio(" ".join(a), " ".join(b)) >= 80
            if not (prefix_hit or whole_hit):
                continue
            span = q.start - p.start
            conf = 0.95 if (truncated_copy or whole_hit) else 0.8
            if span > 25:
                conf -= 0.25
            if span > 50:
                conf -= 0.2
            how = "repeats" if whole_hit else f"starts the same way ({m} words)"
            cands.append(Candidate(
                words=(p.w0, q.w0 - 1), type="retake", confidence=round(conf, 2),
                reason=f"P{p.id} {how} as P{q.id}, so everything from P{p.id} up to P{q.id} is the failed take",
                accept=conf >= 0.7, keeper=q.w0, extra={"phrase": p.id, "keeper_phrase": q.id, "span_s": round(span, 1)},
            ))
            break
    return cands


def detect_word_restarts(words: list[dict], toks: list[str], phrase_of: list[int]) -> list[Candidate]:
    """Restarts inside a phrase or across a short pause: "this is the — this is the map",
    "the map of… map of every agent" (backtrack), and stutters "the the"."""
    cands = []
    n_words = len(words)
    j = 1
    while j < n_words:
        best = None
        for i in range(max(0, j - 20), j):
            n = 0
            while j + n < n_words and i + n < j and toks[i + n] and toks[i + n] == toks[j + n]:
                n += 1
            if n == 0:
                continue
            if best is None or n > best[1] or (n == best[1] and i > best[0]):
                best = (i, n)
        if best:
            i, n = best
            between = range(i + n - 1, j)  # gaps between end of first copy and start of second
            max_gap = max((words[k + 1]["start"] - words[k]["end"] for k in between), default=0.0)
            filler_between = any(toks[k] in FILLERS for k in range(i + n, j))
            loose = j - (i + n)  # words between the two copies
            stop_only = all(t in STOP for t in toks[j:j + n])
            accept = conf = None
            if n >= 2 and loose <= 4 and (max_gap >= 0.15 or filler_between or loose == 0):
                conf = 0.85 if not stop_only else 0.6
            elif n >= 3 and loose <= 8 and max_gap >= 0.25:
                conf = 0.7
            elif n == 1 and loose == 0 and toks[j] in STUTTER_OK:
                conf = 0.75
            if conf:
                # backtrack = the repeated words started mid-phrase ("the map of… map of every agent")
                kind = "stutter" if n == 1 else ("backtrack" if i != phrase_of[i] else "restart")
                accept = conf >= 0.7
                cands.append(Candidate(
                    words=(i, j - 1), type=kind, confidence=conf,
                    reason=f"\"{' '.join(w['w'] for w in words[i:j + n])}\": second copy of \"{' '.join(toks[j:j + n])}\" replaces the first",
                    accept=accept, keeper=j,
                ))
                j += n
                continue
        j += 1
    return cands


def detect_markers(phrases: list[Phrase]) -> list[Candidate]:
    cands = []
    for p in phrases:
        low = " ".join(p.toks)
        content = _content(p.toks)
        if not content:
            continue
        strong = [m for m in STRONG_MARKERS if re.search(m, low)]
        if strong and len(content) <= 6:
            cands.append(Candidate(
                words=(p.w0, p.w1), type="marker", confidence=0.8 if len(content) <= 4 else 0.6,
                reason=f"P{p.id} sounds like a note-to-self (\"{p.text}\"). The phrase before it is probably a failed take too",
                accept=len(content) <= 4, extra={"phrase": p.id},
            ))
        elif len(content) <= 2 and all(t in WEAK_MARKERS for t in content) and p.gap_before > 0.6 and p.gap_after > 0.4:
            cands.append(Candidate(
                words=(p.w0, p.w1), type="marker", confidence=0.5,
                reason=f"P{p.id} \"{p.text}\" stands alone between pauses (reset word?)",
                accept=False, extra={"phrase": p.id},
            ))
    return cands


def detect_fillers(words: list[dict], toks: list[str]) -> list[Candidate]:
    cands = []
    n = len(words)
    for k, t in enumerate(toks):
        if t not in FILLERS:
            continue
        gb = words[k]["start"] - words[k - 1]["end"] if k > 0 else 9.0
        ga = words[k + 1]["start"] - words[k]["end"] if k < n - 1 else 9.0
        if gb >= 0.12 or ga >= 0.12:
            cands.append(Candidate(words=(k, k), type="filler", confidence=0.85,
                                   reason=f"filler \"{words[k]['w']}\" next to a pause", accept=True))
        else:
            cands.append(Candidate(words=(k, k), type="filler", confidence=0.4,
                                   reason=f"filler \"{words[k]['w']}\" glued to speech, cutting it may sound clipped",
                                   accept=False))
    return cands


def detect_fragments(phrases: list[Phrase], covered: set[int]) -> list[Candidate]:
    """A phrase that stops mid-sentence before a long pause: either an abandoned take
    (cut) or a thinking pause inside one sentence (keep, close the gap). Claude decides."""
    cands = []
    for pi, p in enumerate(phrases[:-1]):
        if p.ends_sentence or p.gap_after < 0.6 or p.w0 in covered:
            continue
        nxt = phrases[pi + 1]
        cands.append(Candidate(
            words=(p.w0, p.w1), type="fragment?", confidence=0.4,
            reason=f"P{p.id} stops without ending the sentence, then {p.gap_after:.1f}s pause, then P{nxt.id} "
                   f"\"{nxt.text[:50]}\". Abandoned take (cut) or the same sentence continuing (keep)?",
            accept=False, extra={"phrase": p.id, "next_phrase": nxt.id},
        ))
    return cands


def _dedupe(cands: list[Candidate]) -> list[Candidate]:
    """Drop candidates fully contained in an accepted, higher-confidence one."""
    cands.sort(key=lambda c: (c.words[0], -(c.words[1] - c.words[0])))
    kept: list[Candidate] = []
    for c in cands:
        if any(k.accept and k.words[0] <= c.words[0] and c.words[1] <= k.words[1] for k in kept):
            continue
        kept.append(c)
    for n, c in enumerate(kept, 1):
        c.id = f"C{n}"
    return kept


DEFAULT_SETTINGS = {
    "tighten_pauses": True,
    "sentence_gap_over": 0.7,   # pauses after a full sentence longer than this…
    "sentence_gap_to": 0.30,    # …are shortened to this
    "comma_gap_over": 0.5,
    "comma_gap_to": 0.20,
    "mid_gap_over": 0.40,       # thinking pause inside a sentence longer than this…
    "mid_gap_to": None,         # …is closed to the speaker's natural word gap (auto) unless set
    "head_s": 0.30,             # silence kept before the first word
    "tail_s": 0.50,             # and after the last word
}


def analyze(project: Project) -> dict:
    words = load_words(project)
    if not words:
        raise SystemExit("No words transcribed.")
    toks = [norm_token(w["w"]) for w in words]
    phrases = build_phrases(words)
    phrase_of = [0] * len(words)
    for p in phrases:
        for k in range(p.w0, p.w1 + 1):
            phrase_of[k] = p.w0
    nat = natural_gap(words)

    cands = detect_restarts(phrases)
    cands += detect_word_restarts(words, toks, phrase_of)
    cands += detect_markers(phrases)
    cands += detect_fillers(words, toks)
    covered = {k for c in cands if c.accept for k in range(c.words[0], c.words[1] + 1)}
    cands += detect_fragments(phrases, covered)
    cands = _dedupe(cands)

    # Pauses worth knowing about (for tightening + mid-sentence joins)
    pauses = []
    for k in range(len(words) - 1):
        g = words[k + 1]["start"] - words[k]["end"]
        if g >= REPORT_GAP:
            pauses.append({"after_word": k, "gap": round(g, 3), "kind": punct_class(words[k]["w"])})

    flags = []
    for w in words:
        if w.get("recovered"):
            flags.append({"word": w["i"], "kind": "recovered", "note": "Whisper skipped this speech; recovered in a 2nd pass"})
        elif w["end"] - w["start"] > 1.2 and len(norm_token(w["w"])) <= 8:
            flags.append({"word": w["i"], "kind": "stretched",
                          "note": f"\"{w['w']}\" lasts {w['end'] - w['start']:.1f}s: words may be missing here"})

    analysis = {
        "natural_gap": nat,
        "phrases": [p.__dict__ for p in phrases],
        "candidates": [c.__dict__ for c in cands],
        "pauses": pauses,
        "flags": flags,
    }
    save_json(project.work / "analysis.json", analysis)

    decisions_path = project.work / "decisions.json"
    decisions = {
        "settings": {**DEFAULT_SETTINGS, "natural_gap": nat},
        "cuts": [
            {"id": c.id, "words": list(c.words), "type": c.type, "accept": c.accept,
             "confidence": c.confidence, "reason": c.reason}
            for c in cands
        ],
        "extra_cuts": [],      # [[first_word, last_word, "reason"], …] added in review
        "force_keep": [],      # [[first_word, last_word], …] never cut these
        "gap_kinds": {},       # {"<after_word>": "sentence" | "comma" | "mid" | "keep"}
        "reviewed": False,
    }
    save_json(decisions_path, decisions)
    write_candidates_md(project, words, phrases, cands, pauses, flags, nat)
    return analysis


# ---------------------------------------------------------------- report for the decide step

def _indexed(words: list[dict], a: int, b: int) -> str:
    return " ".join(f"{words[k]['w']}`{k}`" for k in range(a, b + 1))


def write_candidates_md(project, words, phrases, cands, pauses, flags, nat) -> None:
    icon = {True: "✂️", False: "❓"}
    by_word: dict[int, list[Candidate]] = {}
    for c in cands:
        for k in range(c.words[0], c.words[1] + 1):
            by_word.setdefault(k, []).append(c)
    involved = {p.id for p in phrases if any(k in by_word for k in range(p.w0, p.w1 + 1))}
    pause_after = {p["after_word"]: p for p in pauses}
    flagged = {f["word"]: f for f in flags}

    lines = [
        f"# Cut candidates: {project.name}",
        "",
        f"{len(words)} words · {len(phrases)} phrases · {fmt_time(words[-1]['end'])} of speech · "
        f"natural word gap {int(nat * 1000)} ms",
        "",
        "Legend: ✂️ proposed cut (accept=true) · ❓ needs a decision (accept=false) · "
        "`n` = word index · ⏸ pause after the phrase (sentence / comma / **mid** = mid-sentence pause).",
        "Cut words are shown as ~~struck~~ in the transcript.",
        "",
        "## Candidates",
        "",
    ]
    for c in cands:
        a, b = c.words
        after = words[b + 1]["w"] if b + 1 < len(words) else ""
        lines.append(f"- **{c.id}** {icon[c.accept]} `{c.type}` ({c.confidence:.2f}) words {a}–{b} · "
                     f"{fmt_time(words[a]['start'])}–{fmt_time(words[b]['end'])}")
        lines.append(f"  - cut: \"{' '.join(w['w'] for w in words[a:b + 1])[:220]}\"")
        ctx_after = " ".join(w["w"] for w in words[b + 1:b + 14])
        lines.append(f"  - then: \"{ctx_after}…\"" if after else "  - then: (end)")
        lines.append(f"  - why: {c.reason}")
    mids = [p for p in pauses if p["kind"] == "mid" and p["gap"] > DEFAULT_SETTINGS["mid_gap_over"]
            and not any(c.accept for c in by_word.get(p["after_word"], []) + by_word.get(p["after_word"] + 1, []))]
    if mids:
        lines += ["", "## Mid-sentence pauses (will be closed to the natural word gap)", "",
                  "Whisper often drops the period at a pause. If a line below is really a sentence break, "
                  "set `gap_kinds[\"<n>\"] = \"sentence\"` (or `\"keep\"` to leave the pause alone).", ""]
        for p in mids:
            k = p["after_word"]
            before = " ".join(w["w"] for w in words[max(0, k - 7):k + 1])
            after = " ".join(w["w"] for w in words[k + 1:k + 8])
            lines.append(f"- `{k}` {fmt_time(words[k]['end'])} …{before} ⏸{p['gap']:.1f}s {after}…")
    if flags:
        lines += ["", "## Flags (check these spots)", ""]
        for f in flags:
            w = words[f["word"]]
            lines.append(f"- ⚠️ word {f['word']} \"{w['w']}\" at {fmt_time(w['start'])}: {f['note']}")

    lines += ["", "## Transcript", ""]
    for p in phrases:
        parts = []
        for k in range(p.w0, p.w1 + 1):
            txt = words[k]["w"] + (" ⚠️" if k in flagged else "")
            cut_by = [c for c in by_word.get(k, []) if c.accept]
            parts.append(f"~~{txt}~~" if cut_by else txt)
        tag = ""
        cs = sorted({c.id for k in range(p.w0, p.w1 + 1) for c in by_word.get(k, [])})
        if cs:
            tag = " ← " + ", ".join(cs)
        pz = pause_after.get(p.w1)
        ptxt = ""
        if pz:
            kind = "**mid**" if pz["kind"] == "mid" else pz["kind"]
            ptxt = f"  ⏸ {pz['gap']:.2f}s {kind}"
        lines.append(f"**P{p.id}** `{fmt_time(p.start)}` `[{p.w0}–{p.w1}]` {' '.join(parts)}{tag}{ptxt}")
        if p.id in involved:
            lines.append(f"    ↳ {_indexed(words, p.w0, p.w1)}")
        # mid-phrase pauses (between PHRASE_GAP and REPORT_GAP they stay inside the phrase)
        inner = [pause_after[k] for k in range(p.w0, p.w1) if k in pause_after]
        for pz in inner:
            lines.append(f"    ⏸ {pz['gap']:.2f}s {pz['kind']} after `{pz['after_word']}` \"{words[pz['after_word']]['w']}\"")
    (project.work / "candidates.md").write_text("\n".join(lines) + "\n")


def load_decisions(project: Project) -> dict:
    return load_json(project.work / "decisions.json")
