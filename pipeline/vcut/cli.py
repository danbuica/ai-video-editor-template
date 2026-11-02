"""vcut: retake-aware cutter. Run `vcut --help`."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .common import PROJECTS, Project, fmt_time, load_json, snapshot


def cmd_new(p: Project, args) -> None:
    for d in ("inputs", "work", "out"):
        (p.dir / d).mkdir(parents=True, exist_ok=True)
    print(f"Created {p.dir}\nLink the recordings: vcut link {p.name} talking|screen|audio <file>")


def cmd_link(p: Project, args) -> None:
    """inputs/<role>.<ext> → the original recording, as a symlink (works on macOS, Linux and Windows): the original
    is never copied, moved or written. Windows needs Developer Mode on for symlinks (`vcut setup` checks)."""
    src = Path(args.file).expanduser().resolve()
    if not src.is_file():
        raise SystemExit(f"Not a file: {src}")
    p.inputs.mkdir(parents=True, exist_ok=True)
    dst = p.inputs / f"{args.role}{src.suffix.lower()}"
    for old in p.inputs.glob(f"{args.role}.*"):
        if old.is_symlink():
            old.unlink()  # re-pointing a link never touches the file behind it
        else:
            raise SystemExit(f"{old} is a real file, not a link: move it out of inputs/ yourself first.")
    try:
        os.symlink(src, dst)
    except OSError as e:
        raise SystemExit(f"Couldn't create the link ({e}). On Windows, turn on Developer Mode (Settings → System → "
                         f"For developers) and run this again.")
    print(f"{dst} → {src}")


def cmd_probe(p: Project, args) -> None:
    from .probe import probe
    r = probe(p, fps=args.fps, until=getattr(args, "until", None))
    for name in ("talking", "screen"):
        t = r[name]
        print(f"{name:8}: {t['width']}x{t['height']} {t['avg_frame_rate']}fps {'VFR' if t['vfr'] else 'CFR'} "
              f"{fmt_time(t['duration'])}  starts at {r['starts_on_master'][name]:+.3f}s on the master clock")
    if "audio" in r:
        print(f"audio   : {r['audio']['audio']['sample_rate']} Hz {fmt_time(r['audio']['duration'])} (master)")
    for name, sinfo in r["sync"].items():
        print(f"sync {name}: {sinfo['source']}" + (f", drift {sinfo['drift_ms_over_file']} ms over the file" if "drift_ms_over_file" in sinfo else ""))
    print(f"shared window on master: {fmt_time(r['window'][0])} → {fmt_time(r['window'][1])} · output grid {r['fps']} fps")
    for w in r["warnings"]:
        print(f"⚠️  {w}")


def cmd_transcribe(p: Project, args) -> None:
    from .transcribe import recover_only, transcribe
    if getattr(args, "recover_only", False):
        recover_only(p, model_name=args.model, language=args.language)
    else:
        transcribe(p, model_name=args.model, language=args.language, chunk_size=args.chunk)


def cmd_analyze(p: Project, args) -> None:
    from .analyze import analyze
    a = analyze(p)
    acc = sum(1 for c in a["candidates"] if c["accept"])
    print(f"{len(a['phrases'])} phrases, {len(a['candidates'])} candidates ({acc} proposed cuts), "
          f"{len(a['flags'])} flags. Natural gap {int(a['natural_gap'] * 1000)} ms")
    print(f"→ review {p.work / 'candidates.md'} and edit {p.work / 'decisions.json'}")


def cmd_words(p: Project, args) -> None:
    from .transcribe import load_words
    words = load_words(p)
    a, b = args.start, min(args.end, len(words) - 1)
    for w in words[a:b + 1]:
        flag = " (recovered)" if w.get("recovered") else ""
        print(f"{w['i']:>5}  {fmt_time(w['start'])}–{fmt_time(w['end'])}  {w['w']}{flag}")


def cmd_phrases(p: Project, args) -> None:
    """Compact transcript for the decide step: one phrase per line, ~cut ?unsure, word range, gap after."""
    from .analyze import load_decisions
    from .transcribe import load_words
    a = load_json(p.work / "analysis.json")
    words, d = load_words(p), load_decisions(p)
    cut, unsure = set(), set()
    for c in d["cuts"]:
        for k in range(c["words"][0], c["words"][1] + 1):
            (cut if c["accept"] else unsure).add(k)
    for ph in a["phrases"]:
        if not (args.start <= ph["id"] <= args.end):
            continue
        ks = range(ph["w0"], ph["w1"] + 1)
        txt = " ".join(("~" if k in cut else "?" if k in unsure else "") + words[k]["w"] for k in ks)
        if args.indexed:
            txt = " ".join(f"{words[k]['w']}`{k}`" for k in ks)
        print(f"P{ph['id']} {fmt_time(ph['start'])} [{ph['w0']}-{ph['w1']}] {txt}  |{ph['gap_after']:.1f}")


def cmd_keep(p: Project, args) -> None:
    """Apply an explicit keep-list (lines: 'first_word last_word label'): everything else is cut."""
    from .common import save_json
    from .transcribe import load_words
    rows = [l.split(None, 2) for l in open(args.file) if l.strip() and not l.lstrip().startswith("#")]
    keeps = sorted((int(r[0]), int(r[1]), (r[2] if len(r) > 2 else "").strip()) for r in rows)
    prev = -1
    for a_, b_, lab in keeps:
        if a_ <= prev or b_ < a_:
            sys.exit(f"keep ranges overlap or are reversed at {a_}-{b_} ({lab})")
        prev = b_
    n = len(load_words(p))
    d = load_json(p.work / "decisions.json")
    for c in d["cuts"]:
        c["accept"] = False
    extra, cur = [], 0
    for a_, b_, _ in keeps:
        if a_ > cur:
            extra.append([cur, a_ - 1, "not in keep-list"])
        cur = b_ + 1
    if cur < n:
        extra.append([cur, n - 1, "not in keep-list"])
    d.update({"extra_cuts": extra, "_keeps": keeps, "reviewed": True})
    save_json(p.work / "decisions.json", d)
    print(f"{len(keeps)} keep ranges, {sum(b_ - a_ + 1 for a_, b_, _ in keeps)} of {n} words kept")


def cmd_transcript(p: Project, args) -> None:
    """Timestamped transcript of the FINAL cut (out/transcript_final.md). ‖ marks where words were removed."""
    data = load_json(p.out / "transcript_cut.json")["words"]
    layout = load_json(p.out / "layout.json") if (p.out / "layout.json").exists() else {"full": []}
    lines, cur = [], []
    for i, w in enumerate(data):
        cur.append(w)
        nxt = data[i + 1] if i + 1 < len(data) else None
        if nxt is None or w["w"].rstrip('"').endswith((".", "?", "!")) or nxt["start"] - w["end"] > 0.6:
            lines.append(cur)
            cur = []
    out = [f"# {p.name}: final cut transcript", "",
           "Times are positions in the final video. `‖` = words were cut here. 🎥 = full-screen talking head.", ""]
    for ln in lines:
        parts = []
        for j, w in enumerate(ln):
            prev = ln[j - 1] if j else None
            if prev is not None and w["src_i"] != prev["src_i"] + 1:
                parts.append("‖")
            parts.append(w["w"])
        s = ln[0]["start"]
        cam = " 🎥" if any(r["from"] <= s < r["to"] for r in layout.get("full", [])) else ""
        out.append(f"`{fmt_time(s)}`{cam} {' '.join(parts)}")
        out.append("")
    (p.out / "transcript_final.md").write_text("\n".join(out))
    print(f"→ {p.out / 'transcript_final.md'} ({len(lines)} lines)")


def _final_shift(p: Project):
    """Map a cut-timeline second to the FINAL timeline (inserted chapter cards push later content back)."""
    plan_path = p.out / "motion.json"
    plan = load_json(plan_path) if plan_path.exists() else {}
    words = {w["src_i"]: w for w in load_json(p.out / "transcript_cut.json")["words"]}
    fps = load_json(p.out / "edl.json")["fps_float"]
    card = plan.get("chapterSeconds", 2)
    chapters = []
    for c in plan.get("chapters", []):
        at = c["at"]
        if isinstance(at, (int, float)):  # plain cut-timeline seconds (e.g. a join time from make_plan.py)
            cut_t = round(at * fps) / fps
        else:
            w = words.get(at["w"]) or next(words[k] for k in sorted(words) if k > at["w"])
            cut_t = round((w["start"] + at.get("pad", 0)) * fps) / fps
        chapters.append((cut_t, c["title"]))
    chapters.sort()

    def shift(t: float) -> float:
        return t + card * sum(1 for ct, _ in chapters if ct <= t + 1e-6)
    # a chapter's timestamp = the start of its card (the card sits just before the chapter content)
    final_chapters = [(ct + card * i, title) for i, (ct, title) in enumerate(chapters)]
    return shift, final_chapters, words


def _ts(t: float) -> str:
    t = int(t)
    h, m, s = t // 3600, (t % 3600) // 60, t % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def cmd_chapters(p: Project, args) -> None:
    """YouTube chapters with REAL timestamps on the final timeline (chapter cards included), validated against
    YouTube's rules. --transcript also writes the final-timeline transcript for picking chapters by topic."""
    shift, chapters, words = _final_shift(p)
    if args.transcript or not chapters:
        rows, cur = [], []
        ws = [words[k] for k in sorted(words)]
        for i, w in enumerate(ws):
            cur.append(w)
            nxt = ws[i + 1] if i + 1 < len(ws) else None
            if nxt is None or w["w"].rstrip('"').endswith((".", "?", "!")) or nxt["start"] - w["end"] > 0.6:
                rows.append(f"[{_ts(shift(cur[0]['start']))}] " + " ".join(x["w"] for x in cur))
                cur = []
        (p.out / "transcript_final_timeline.md").write_text("\n".join(rows) + "\n")
        print(f"→ {p.out / 'transcript_final_timeline.md'} (timestamps as in the final video)")
    if not chapters:
        print("No chapter cards in motion.json: pick chapters from the transcript above.")
        return
    lines = [(0.0, args.intro)] + chapters
    problems = []
    if len(lines) < 3:
        problems.append("YouTube needs at least 3 chapters")
    for (a, ta), (b, tb) in zip(lines, lines[1:]):
        if b - a < 10:
            problems.append(f"'{ta}' is shorter than 10 s ({b - a:.1f} s): YouTube will ignore all chapters")
    text = "\n".join(f"{_ts(t)} {title}" for t, title in lines)
    (p.out / "youtube_chapters.txt").write_text(text + "\n")
    print(text)
    print(f"→ {p.out / 'youtube_chapters.txt'}")
    for pr in problems:
        print(f"⚠️  {pr}")


def cmd_text(p: Project, args) -> None:
    """Print the script as it will read after the current decisions."""
    from .edl import _cut_set
    from .analyze import load_decisions
    from .transcribe import load_words
    words = load_words(p)
    cut, _ = _cut_set(load_decisions(p), len(words))
    out, in_cut = [], False
    for k, w in enumerate(words):
        if k in cut:
            if not in_cut and args.marks:
                out.append("✂")
            in_cut = True
            continue
        in_cut = False
        out.append(w["w"])
    print(" ".join(out))


def cmd_edl(p: Project, args) -> None:
    from .edl import build_edl
    e = build_edl(p)
    print(f"{fmt_time(e['source_s'])} → {fmt_time(e['out_s'])} · {len(e['segments'])} segments · {len(e['joins'])} joins")
    print(f"→ {p.out / 'review.md'}")


def cmd_render(p: Project, args) -> None:
    from .render import render
    render(p, encoder=args.encoder, only=args.only, talking_height=args.talking_height or None)


def cmd_proxy(p: Project, args) -> None:
    from .render import make_proxy
    for name in ([args.only] if args.only else ["talking", "screen"]):
        make_proxy(p, name)


def cmd_qa(p: Project, args) -> None:
    from .qa import qa
    qa(p, src=args.src, model_name=args.model, diff=not args.no_diff)


def cmd_export(p: Project, args) -> None:
    from .housekeeping import export
    export(p, src=args.src, dest_dir=args.dest)


def cmd_clean(p: Project, args) -> None:
    from .housekeeping import clean
    clean(p, yes=args.yes, skip_export_check=args.skip_export_check)


def cmd_verify(p: Project, args) -> None:
    from .verify import verify
    r = verify(p, asr=args.asr)
    sys.exit(0 if r["ok"] else 1)


def cmd_prepare(p: Project, args) -> None:
    cmd_probe(p, args)
    if args.skip_transcribe and (p.work / "words.json").exists():
        print("[transcribe] reusing words.json")
    else:
        cmd_transcribe(p, args)
    cmd_analyze(p, args)


def cmd_build(p: Project, args) -> None:
    d = load_json(p.work / "decisions.json")
    if not d.get("reviewed") and not args.force:
        sys.exit("decisions.json has reviewed=false. Review candidates first (or pass --force).")
    cmd_edl(p, args)
    cmd_render(p, args)
    cmd_verify(p, args)


def main() -> None:
    ap = argparse.ArgumentParser(prog="vcut", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("project", help=f"project folder name under {PROJECTS}")
        sp.set_defaults(fn=fn)
        return sp

    sub.add_parser("setup", help="detect this computer's GPU / video encoder → hardware.json (run once after install)")
    add("new", cmd_new, "create a project folder")
    sp = add("link", cmd_link, "link a recording into the project's inputs/ (never copies or touches it)")
    sp.add_argument("role", help="talking, screen, audio (or e.g. phone1, audio_raw)")
    sp.add_argument("file")
    sp = add("probe", cmd_probe, "inspect inputs, sync them, extract master audio")
    sp.add_argument("--fps", help="output frame rate, e.g. 30 or 30000/1001 (default: talking head's)")
    sp.add_argument("--until", type=float, help="only process the first N seconds of the shared window")
    sp = add("transcribe", cmd_transcribe, "WhisperX transcription with word timing")
    for s in (sp,):
        s.add_argument("--model", default="large-v3")
        s.add_argument("--language", default="en")
        s.add_argument("--chunk", type=int, default=15, help="max seconds per ASR chunk (smaller = more verbatim)")
        s.add_argument("--recover-only", action="store_true", help="re-run only the recovery pass on words_main.json")
    add("analyze", cmd_analyze, "phrases, pauses and retake candidates → candidates.md + decisions.json")
    sp = add("words", cmd_words, "print words with indices")
    sp.add_argument("start", type=int)
    sp.add_argument("end", type=int)
    sp = add("phrases", cmd_phrases, "compact phrase list for the decide step (~cut ?unsure)")
    sp.add_argument("start", type=int, nargs="?", default=1)
    sp.add_argument("end", type=int, nargs="?", default=10**9)
    sp.add_argument("--indexed", action="store_true", help="show every word with its index")
    sp = add("keep", cmd_keep, "apply a keep-list file: keep only these word ranges")
    sp.add_argument("file")
    add("transcript", cmd_transcript, "timestamped transcript of the final cut → out/transcript_final.md")
    sp = add("chapters", cmd_chapters, "YouTube chapters with real final-video timestamps (+ validation)")
    sp.add_argument("--transcript", action="store_true", help="also write the final-timeline transcript")
    sp.add_argument("--intro", default="Intro", help="title of the 0:00 chapter")
    sp = add("text", cmd_text, "print the script after current decisions")
    sp.add_argument("--marks", action="store_true", help="show ✂ where cuts happen")
    add("edl", cmd_edl, "build out/edl.json + review.md from decisions")
    sp = add("render", cmd_render, "render talking_cut.mp4 + screen_cut.mp4")
    sp.add_argument("--encoder", default="auto", choices=["auto", "hevc", "x264"])
    sp.add_argument("--talking-height", type=int, default=1440, help="downscale the camera to this height (0 = keep source)")
    sp.add_argument("--only", choices=["talking", "screen"])
    sp = add("proxy", cmd_proxy, "(re)build the 720p draft proxies in out/proxy/ (render does this automatically)")
    sp.add_argument("--only", choices=["talking", "screen"])
    sp = add("qa", cmd_qa, "listen to the finished cut (independent re-transcription) and flag likely problems → out/qa.md")
    sp.add_argument("--src", help="audio/video to check (default work/cut_master.wav = the current cut)")
    sp.add_argument("--model", default="large-v3")
    sp.add_argument("--no-diff", action="store_true", help="skip the word diff (when --src isn't the current cut)")
    sp = add("export", cmd_export, "copy the final (+ chapters/description) into export/ next to the original recordings")
    sp.add_argument("--src", help="file to export (default out/<name>_final_4k.mp4)")
    sp.add_argument("--dest", help="export folder (default: <originals folder>/export)")
    sp = add("clean", cmd_clean, "delete big regenerable media (dry run unless --yes); needs a verified export")
    sp.add_argument("--yes", action="store_true", help="actually delete")
    sp.add_argument("--skip-export-check", action="store_true")
    sp = add("verify", cmd_verify, "frame counts, joins in silence, sync")
    sp.add_argument("--asr", action="store_true", help="also re-transcribe the cut and compare (slow)")
    sp = add("prepare", cmd_prepare, "probe + transcribe + analyze")
    sp.add_argument("--fps")
    sp.add_argument("--until", type=float, help="only process the first N seconds (e.g. just the hook)")
    sp.add_argument("--model", default="large-v3")
    sp.add_argument("--language", default="en")
    sp.add_argument("--chunk", type=int, default=15)
    sp.add_argument("--skip-transcribe", action="store_true", help="reuse existing words.json")
    sp = add("build", cmd_build, "edl + render + verify")
    sp.add_argument("--encoder", default="auto", choices=["auto", "hevc", "x264"])
    sp.add_argument("--talking-height", type=int, default=1440)
    sp.add_argument("--only", choices=["talking", "screen"])
    sp.add_argument("--asr", action="store_true")
    sp.add_argument("--force", action="store_true")

    args = ap.parse_args()
    if args.cmd == "setup":
        from . import hw
        hw.setup()
        return
    if args.cmd in ("prepare", "transcribe", "render", "build", "qa"):
        from . import hw
        hw.keep_awake()
    project = Project(args.project)
    before = snapshot(project.originals())
    try:
        args.fn(project, args)
    finally:
        after = snapshot(project.originals())
        changed = [p for p in before if before[p] != after.get(p)]
        if changed:
            print(f"🚨 ORIGINAL FILES CHANGED: {changed}", file=sys.stderr)
            sys.exit(3)


if __name__ == "__main__":
    main()
