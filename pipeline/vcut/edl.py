"""Stage 5→6: turn word-level decisions into a frame-exact edit list shared by BOTH videos.

Every join is placed inside real silence (from the loudness envelope, not the aligner's word ends),
and the silence left at the join is sized by its kind:
  sentence break → ~0.3s · comma → ~0.2s · mid-sentence (thinking pause, backtrack) → the speaker's own word gap.
Audio and video are cut on the same frame boundaries, so lip sync can never drift.
"""
from __future__ import annotations

import math
from fractions import Fraction

import numpy as np

from .analyze import load_decisions, punct_class
from .audio import Envelope
from .common import Project, fmt_time, load_json, save_json
from .transcribe import load_words

MIN_RUN = 0.06       # a silence must last this long to count as a pause (skips stop-consonant closures)
TAIL_MIN = 0.06      # never keep less than this after a word's last audible sound (release / decay)
PRE_MIN = 0.04       # never keep less than this before a word's onset (plosive burst / breathy onset)
HARD_TAIL = 0.03     # frame rounding may never eat into these
HARD_PRE = 0.02
CONTINUES = {"that", "which", "who", "whom", "whose", "will", "would", "to", "of", "for", "with", "than", "because",
             "where", "when", "while", "if", "is", "are", "was", "were", "means", "mean"}
PAUSE_EDGE_DB = 16.0  # pause edges: smoothed loudness below floor + this counts as quiet


class Pauses:
    def __init__(self, words: list[dict], env: Envelope):
        self.words = words
        self.env = env
        self._cache: dict[int, tuple[float, float] | None] = {}

    def after(self, k: int) -> tuple[float, float] | None:
        """Removable silence between word k and k+1: (end of k's sound, onset of k+1).
        Breaths inside a pause count as removable: we take the first silent run after k
        and the last silent run before k+1."""
        if k in self._cache:
            return self._cache[k]
        w, n = self.words[k], self.words[k + 1]
        dur_w = max(0.0, w["end"] - w["start"])
        dur_n = max(0.0, n["end"] - n["start"])
        r0 = max(w["start"] + 0.6 * dur_w, w["end"] - 0.25)
        r1 = min(n["start"] + 0.4 * dur_n, n["start"] + 0.15)
        res = None
        if r1 - r0 > MIN_RUN:
            env = self.env
            a, b = env.i(r0), env.i(r1)
            # room tone in pauses (-47..-53 dB) sat on the global threshold (8th-percentile floor of the whole
            # recording + 10 dB), so pauses went undetected and joins kept 0.1-1.0 s at random. Pause edges use the
            # envelope smoothed over 25 ms against floor + 16 dB (speech is 20-30 dB louder than that).
            seg = env.db[max(0, a - 2): b + 3]
            sm = np.array([np.median(seg[k:k + 5]) for k in range(len(seg) - 4)])[: b - a] if len(seg) > 5 else env.db[a:b]
            mask = sm < max(env.thr, env.floor + PAUSE_EDGE_DB)
            need = max(1, int(round(MIN_RUN / 0.005)))
            runs, start = [], None
            for i, s in enumerate(np.append(mask, False)):
                if s and start is None:
                    start = i
                elif not s and start is not None:
                    if i - start >= need:
                        runs.append((start, i))
                    start = None
            gap = n["start"] - w["end"]
            # Edges: the first quiet run after A's sound, the last quiet run before B's onset.
            # Only runs near the words count, so clicks/noise in the middle of a long pause don't matter.
            near_a = [r for r in runs if env.t(a + r[0]) <= w["end"] + 0.35]
            near_b = [r for r in runs if env.t(a + r[1]) >= n["start"] - 0.35]
            off = env.t(a + near_a[0][0]) if near_a else (w["end"] + 0.05 if gap > 0.4 else None)
            on = env.t(a + near_b[-1][1]) if near_b else (n["start"] - 0.04 if gap > 0.4 else None)
            if off is not None and on is not None and on - off >= MIN_RUN:
                res = (off, on)
        self._cache[k] = res
        return res


def _cut_set(decisions: dict, n_words: int) -> tuple[set[int], dict[int, dict]]:
    cut: set[int] = set()
    why: dict[int, dict] = {}
    for c in decisions["cuts"]:
        if c.get("accept"):
            for k in range(c["words"][0], c["words"][1] + 1):
                cut.add(k)
                why.setdefault(k, c)
    for item in decisions.get("extra_cuts", []):
        a, b = item[0], item[1]
        reason = item[2] if len(item) > 2 else "manual"
        for k in range(a, b + 1):
            cut.add(k)
            why.setdefault(k, {"id": "manual", "type": "manual", "reason": reason})
    for a, b in decisions.get("force_keep", []):
        for k in range(a, b + 1):
            cut.discard(k)
            why.pop(k, None)
    return {k for k in cut if 0 <= k < n_words}, why


def build_edl(project: Project) -> dict:
    probe = load_json(project.work / "probe.json")
    words = load_words(project)
    decisions = load_decisions(project)
    st = decisions["settings"]
    env = Envelope(np.load(project.work / "envelope.npy"))
    pauses = Pauses(words, env)
    fps = Fraction(probe["fps"])
    total_frames = int(math.floor(probe["duration"] * fps))
    nat = st.get("mid_gap_to") or st.get("natural_gap") or 0.1
    nat = max(nat, TAIL_MIN + PRE_MIN)

    cut, why = _cut_set(decisions, len(words))
    kept = [k for k in range(len(words)) if k not in cut]
    if not kept:
        raise SystemExit("Every word is cut. Check decisions.json.")
    gap_kinds = {int(k): v for k, v in decisions.get("gap_kinds", {}).items()}

    def to_frame(t: float) -> int:
        return int(round(t * fps))

    def ft(f: int) -> float:
        return float(f / fps)

    removals: list[tuple[int, int, dict]] = []  # [start_frame, end_frame) removed from source

    # Head: keep head_s of silence before the first kept word, but never reach back into cut speech
    k0 = kept[0]
    lo = 0.0
    if k0 > 0:
        p = pauses.after(k0 - 1)
        lo = (p[0] + HARD_TAIL) if p else words[k0 - 1]["end"]
    p_on = pauses.after(k0 - 1)[1] if k0 > 0 and pauses.after(k0 - 1) else words[k0]["start"]
    head = max(lo, min(p_on, words[k0]["start"]) - st["head_s"], 0.0)
    if st.get("head_at") is not None:  # a part of a long video: start where the one-video cut joins (parts_split.py edges)
        head = st["head_at"]
    if to_frame(head) > 0:
        removals.append((0, to_frame(head), {"kind": "head", "cut_words": [0, k0 - 1] if k0 > 0 else None,
                                             "before_word": k0}))

    # Tail
    kl = kept[-1]
    hi = probe["duration"]
    if kl < len(words) - 1:
        p = pauses.after(kl)
        hi = (p[1] - HARD_PRE) if p else words[kl + 1]["start"]
    p_off = pauses.after(kl)[0] if kl < len(words) - 1 and pauses.after(kl) else words[kl]["end"]
    tail = min(hi, max(p_off, words[kl]["end"]) + st["tail_s"], probe["duration"])
    if st.get("tail_at") is not None:  # a part: end where the one-video cut joins
        tail = st["tail_at"]
    if to_frame(tail) < total_frames:
        removals.append((to_frame(tail), total_frames, {"kind": "tail", "after_word": kl,
                                                         "cut_words": [kl + 1, len(words) - 1] if kl < len(words) - 1 else None}))

    for a, b in zip(kept, kept[1:]):
        adjacent = b == a + 1
        kind = gap_kinds.get(a) or punct_class(words[a]["w"])
        # the ASR often puts a full stop where the speaker only paused mid-thought ("…add there. That means…"):
        # a word that can only continue the sentence makes it a comma pause, not a sentence pause
        if kind == "sentence" and words[b]["w"].lower().strip('.,?!"“”—') in CONTINUES:
            kind = "comma"
        if kind == "keep" and adjacent:
            continue
        pa = pauses.after(a)
        pb = pauses.after(b - 1)
        # Left side: end of A's sound. Right side: onset of B. "tight" = no pause there (A or B is
        # glued to a cut word), so the cut goes at the quietest 5 ms between the two words.
        tight_a, tight_b = pa is None, pb is None
        if pa:
            off_a, avail_a = pa[0], pa[1] - pa[0]
        else:
            nxt = words[a + 1]["start"]
            off_a, avail_a = env.quietest(min(words[a]["end"], nxt) - 0.05, max(words[a]["end"], nxt) + 0.04), 0.0
        if words[b].get("hard_start"):
            # manual fix: cut exactly at this onset, no pre-roll (e.g. a retake glued to the previous attempt)
            pb, tight_b = None, True
            on_b, avail_b = words[b]["start"], 0.0
        elif pb:
            on_b, avail_b = pb[1], pb[1] - pb[0]
        else:
            prv = words[b - 1]["end"]
            on_b, avail_b = env.quietest(min(words[b]["start"], prv) - 0.04, max(words[b]["start"], prv) + 0.05), 0.0

        if adjacent:
            if not pa:
                continue
            g = on_b - off_a
            if kind == "sentence":
                if not st["tighten_pauses"] or g <= st["sentence_gap_over"]:
                    continue
                target, jtype = st["sentence_gap_to"], "pause"
            elif kind == "comma":
                if not st["tighten_pauses"] or g <= st["comma_gap_over"]:
                    continue
                target, jtype = st["comma_gap_to"], "pause"
            else:
                if g <= st["mid_gap_over"]:
                    continue
                target, jtype = nat, "mid_sentence"
            avail_a = avail_b = g
            source = None
        else:
            target = {"sentence": st["sentence_gap_to"], "comma": st["comma_gap_to"]}.get(kind, nat)
            src = why.get(a + 1) or {}
            jtype = src.get("type", "cut")
            source = src

        # Split the kept silence: a bit more after the word (decay) than before the next (onset)
        x = min(max(TAIL_MIN, target * 0.55), avail_a) if avail_a else 0.0
        y = min(max(PRE_MIN, target - x), avail_b) if avail_b else 0.0
        if x + y < target and avail_a > x:
            x = min(avail_a, target - y)
        a_end, a_start = off_a + x, on_b - y   # ideal audio cut points (ms precision)
        ef, sf = to_frame(a_end), to_frame(a_start)
        # video frame rounding must not eat into speech on the silent sides
        if not tight_a:
            while ft(ef) < off_a + HARD_TAIL:
                ef += 1
        if not tight_b:
            while ft(sf) > on_b - HARD_PRE:
                sf -= 1
        if sf <= ef:
            continue
        removals.append((ef, sf, {
            "kind": jtype, "after_word": a, "before_word": b, "tight": tight_a or tight_b,
            "tight_a": tight_a, "tight_b": tight_b, "a_end": round(a_end, 4), "a_start": round(a_start, 4),
            "cut_words": None if adjacent else [a + 1, b - 1],
            "mid_sentence": kind == "mid",
            "cut_id": source.get("id") if source else None,
            "reason": source.get("reason") if source else f"{kind} pause {on_b - off_a:.2f}s → {target:.2f}s",
            "kept_gap": round(x + y, 3),
        }))

    # Keep segments = complement of removals
    removals.sort(key=lambda r: r[0])
    segments, cursor = [], 0
    joins = []
    for s, e, meta in removals:
        s, e = max(s, cursor), min(e, total_frames)
        if e <= s:
            continue
        if s > cursor:
            segments.append([cursor, s])
        cursor = e
        meta["src_frames"] = [s, e]
        joins.append(meta)
    if cursor < total_frames:
        segments.append([cursor, total_frames])

    out_frames, seg_objs = 0, []
    ends_at = {j["src_frames"][0]: j for j in joins}    # removal starting where a segment ends
    starts_at = {j["src_frames"][1]: j for j in joins}  # removal ending where a segment starts
    half = 0.5 / float(fps)
    for s, e in segments:
        # Audio may slide up to half a frame against video (inaudible/invisible) so a tight
        # cut lands on its exact quietest millisecond instead of the nearest frame edge.
        js, je = starts_at.get(s), ends_at.get(e)
        d_s = (js["a_start"] - ft(s)) if js and js.get("tight_b") else None
        d_e = (je["a_end"] - ft(e)) if je and je.get("tight_a") else None
        cands = [d for d in (d_s, d_e) if d is not None]
        if len(cands) == 2:  # both ends tight: pick the shift that leaves both cut points quietest
            delta = min(cands, key=lambda d: env.db[env.i(ft(s) + d)] + env.db[env.i(ft(e) + d)])
        else:
            delta = cands[0] if cands else 0.0
        delta = max(-half, min(half, delta))
        seg_objs.append({
            "src_start": s, "src_end": e, "out_start": out_frames,
            "src_start_s": round(ft(s), 4), "src_end_s": round(ft(e), 4), "out_start_s": round(ft(out_frames), 4),
            "audio_offset_s": round(delta, 4),
        })
        out_frames += e - s

    def seg_for(t: float) -> dict | None:
        """Segment whose (audio-shifted) source range contains source time t."""
        for sg in seg_objs:
            if sg["src_start_s"] + sg["audio_offset_s"] <= t < sg["src_end_s"] + sg["audio_offset_s"]:
                return sg
        return None

    def src_to_out(t: float, sg: dict) -> float:
        return t - (sg["src_start_s"] + sg["audio_offset_s"]) + sg["out_start_s"]

    # Join positions on the output timeline
    for j in joins:
        s, _ = j["src_frames"]
        prev = next((sg for sg in seg_objs if sg["src_end"] == s), None)
        j["out_frame"] = prev["out_start"] + (prev["src_end"] - prev["src_start"]) if prev else 0
        j["out_s"] = round(ft(j["out_frame"]), 3)
        j["removed_s"] = round(ft(j["src_frames"][1] - j["src_frames"][0]), 3)
        if j.get("after_word") is not None:
            a = j["after_word"]
            j["text_before"] = " ".join(w["w"] for w in words[max(0, a - 6):a + 1])
        if j.get("before_word") is not None:
            b = j["before_word"]
            j["text_after"] = " ".join(w["w"] for w in words[b:b + 6])
        if j.get("cut_words"):
            ca, cb = j["cut_words"]
            j["cut_text"] = " ".join(w["w"] for w in words[ca:cb + 1])

    # Transcript remapped onto the cut timeline
    tw = []
    for k in kept:
        w = words[k]
        sg = seg_for(w["start"]) or seg_for((w["start"] + w["end"]) / 2)
        if sg is None:
            continue
        seg_end = float((sg["out_start"] + sg["src_end"] - sg["src_start"]) / fps)
        s0 = max(sg["out_start_s"], src_to_out(w["start"], sg))
        e0 = min(seg_end, src_to_out(w["end"], sg))
        tw.append({"w": w["w"], "start": round(s0, 3), "end": round(max(s0, e0), 3), "src_i": k})

    edl = {
        "version": 1,
        "fps": str(fps),
        "fps_float": float(fps),
        "source_frames": total_frames,
        "out_frames": out_frames,
        "source_s": round(ft(total_frames), 3),
        "out_s": round(ft(out_frames), 3),
        "natural_gap": nat,
        "segments": seg_objs,
        "joins": joins,
    }
    save_json(project.out / "edl.json", edl)
    save_json(project.out / "transcript_cut.json", {"fps": str(fps), "words": tw})
    write_review(project, edl, words, decisions, cut)
    return edl


def write_review(project: Project, edl: dict, words: list[dict], decisions: dict, cut: set[int]) -> None:
    joins = edl["joins"]
    content = [j for j in joins if j.get("cut_words")]
    mids = [j for j in joins if j["kind"] == "mid_sentence" or j.get("mid_sentence")]
    pauses = [j for j in joins if j["kind"] == "pause"]
    tight = [j for j in joins if j.get("tight")]
    lines = [
        f"# Cut review: {project.name}",
        "",
        f"**{fmt_time(edl['source_s'])} → {fmt_time(edl['out_s'])}** "
        f"({edl['source_s'] - edl['out_s']:.1f}s removed) · {edl['fps']} fps · "
        f"{len(edl['segments'])} segments · {len(cut)} words cut",
        "",
        f"- {len(content)} cuts that remove words (retakes, restarts, fillers)",
        f"- {len(mids)} mid-sentence joins (closed to {int(edl['natural_gap'] * 1000)} ms, the natural word gap)",
        f"- {len(pauses)} long pauses shortened",
        "",
    ]
    if tight:
        lines += ["## ⚠️ Tight joins (no silence at the cut point, so listen to these)", ""]
        for j in tight:
            lines.append(f"- `{fmt_time(j['out_s'])}` …{j.get('text_before', '')} ‖ {j.get('text_after', '')}…")
        lines.append("")
    lines += ["## Removed words", "", "Time = position in the **cut** video where the join happens.", ""]
    for j in content:
        where = {"head": "start of video", "tail": "end of video"}.get(j["kind"], "")
        label = j["kind"] + (" · mid-sentence join" if j.get("mid_sentence") else "") + (f" · {where}" if where else "")
        lines.append(f"- `{fmt_time(j['out_s'])}` ✂️ {label} ({j['removed_s']:.1f}s): ~~{j.get('cut_text', '')[:200]}~~")
        lines.append(f"  - joins: …{j.get('text_before', '')} ‖ {j.get('text_after', '')}…")
    if mids:
        lines += ["", "## Mid-sentence joins (spot-check a few)", ""]
        for j in mids:
            lines.append(f"- `{fmt_time(j['out_s'])}` …{j.get('text_before', '')} ‖ {j.get('text_after', '')}… "
                         f"(removed {j['removed_s']:.2f}s, kept gap {int(j['kept_gap'] * 1000)} ms)")
    lines += ["", "## Final script (what the cut says)", ""]
    kept_text = " ".join(w["w"] for k, w in enumerate(words) if k not in cut)
    lines.append(kept_text)
    (project.out / "review.md").write_text("\n".join(lines) + "\n")
