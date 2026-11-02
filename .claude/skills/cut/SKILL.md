---
name: cut
description: Cut retakes out of raw recordings (camera, screen recording, separate mic — any set of files), sync them, lay them out and render with Remotion. Use when the user says "/cut", "edit this video", "cut this video", "remove the retakes", "do the full video", points at a folder of recordings, or asks to adjust or restore a cut or change the layout of an existing project. By default it runs together with /motion as ONE complete first pass (cut + graphics, chapter cards, music → 720p draft), then a review round on the user's notes (draft 2 + a change list with new timestamps), then the 4K final.
---

# /cut: retake cutter + layout

Each video has up to three files: **talking** (camera, required), **screen** (screen recording, required: for a
talking-head-only video symlink the camera as the screen too and make the whole video `full`), **audio** (separate
mic, optional; it becomes the master audio when present). The editor syncs them, cuts the retakes (**the last
complete take wins**), closes thinking pauses, lays everything out in Remotion and renders.

**Never touch the originals.** Never write next to them, move or rename them. Inputs are symlinks in
`projects/<name>/inputs/`; vcut refuses to write outside `projects/` and checks the originals' size+mtime before and
after every command.

Commands run from the repo root: `uv run --project pipeline vcut <cmd> <project>` (below: `vcut …`). Remotion
commands run from `remotion/`. Long steps (prepare, qa, renders) go in the background with a log.

## Your setup
<!-- CUSTOMIZE: the files each video has (camera / mic / screen), the camera and its frame rate, where recordings live, the language spoken -->
_Empty. Filled in when you customize the editor._

## The flow: one complete first pass, then one review round
**Round 1: everything, then one draft.** Don't stop after the cut to propose graphics.
1. Steps 1–4b below: set up, prepare, keep-list, build, QA (every QA spot gets a verdict).
2. **Editor notes said on camera.** The user can talk to the editor while recording ("Editor, zoom in on me right
   now", "editor, blur my email here", "editor, cut the last line", "put the website here"). Find every one in the
   transcript and do it. "The last line" is the sentence right before the note. Cut the note itself. If no engine
   mechanism fits a note, say so in the report instead of faking it.
3. Layout (step 5), then /motion in the same pass (no proposal round): graphics, chapter cards, music, SFX. Render
   stills of every item and fix what you see. Ask mid-pass only what you truly can't decide.
4. 720p draft (/motion step 4) + `vcut transcript <name>` + `vcut chapters <name>`. Send the draft,
   `out/transcript_final.md` and the report (step 6).

**Round 2: the user's notes, then draft 2.**
1. Back up `keeps.txt`, `out/edl.json`, `out/transcript_cut.json` as `*.v1.*` first. Note times are on the draft
   they watched: `uv run --project pipeline python pipeline/tools/at.py projects/<name> MM:SS --transcript
   out/transcript_cut.v1.json` shows the words there (final-video times, chapter cards included).
2. Apply every note (keep-list, layout, graphics, blurs). A line "cut mid-sentence" is usually a clipped word: check
   with `retx.py` + the loudness envelope, fix with `fixwords.py` (see Traps).
3. `vcut build`, then `uv run --project pipeline python pipeline/tools/joincheck.py projects/<name> <src_i…>` on every
   join you changed. Re-run `facecard.py`, re-render stills of changed items.
4. Render draft 2 and write `out/changes_v2.md`: one row per note with the **new-draft** timestamp (~2 s before the
   change), what was asked, what you did, open questions. Say that removed lines shift everything after them.
5. Final in 4K **only after the user approves** the draft (/motion step 5), then export.

## 1. Set up
- `vcut new <name>`, then `ln -s "<abs path>" projects/<name>/inputs/talking.mp4` (and `screen.mov`, `audio.wav`;
  keep the real extensions). `ffprobe` tells which file is which.
- Sources with sound are synced to the master audio automatically (offset and drift). **A silent screen
  recording** needs `projects/<name>/sync.json`: `{"screen_start": <seconds into the master audio>}`. Find a cue
  (a clap, a tab opened/closed on screen while saying it) in both, average the offsets of several events, render a
  short check clip and ask the user to confirm. Recording with a mic enabled in the screen recorder avoids this.
- **The screen recording may start late** (talking-head intro first). Probe warns "screen covers only …"; that part
  is black on the screen, so it must be `full` talking head in the layout.
- **Extra clips** (phone recordings…): symlink as `inputs/phone1.mp4`, convert to CFR H.264 in `out/`
  (`ffmpeg -i inputs/phone1.mp4 -an -vf fps=30,format=yuv420p -c:v libx264 -crf 18 out/phone1.mp4`). HEVC/VFR clips
  don't decode reliably in Remotion.

## 2. Prepare
Write `projects/<name>/names.txt` first: the tools, products and names said in this video, comma separated. They go
into Whisper's prompt as a spelling hint (only names really said; it is not a script). Then `vcut prepare <name>`
(probe → transcribe → analyze; `--until 600` = first 10 min only, `--language` for non-English). Stop and tell the
user on a weak-sync or drift warning.

## 3. Decide: the explicit keep-list (your job, be careful)
The algorithm's proposals (`work/candidates.md`) are a hint, not the answer. Write an explicit keep-list:
1. `vcut phrases <name> [from] [to]` (`~` = algorithm would cut, `?` = unsure). Read the **whole** transcript.
2. Per line pick the final complete take. Word indices: `vcut phrases <name> <id> <id> --indexed`
   (or `vcut words <name> <i0> <i1>` for times).
3. `projects/<name>/keeps.txt`: one `first_word last_word label` per line (`#` = comment, ranges in order, no
   overlaps). Apply with `vcut keep <name> projects/<name>/keeps.txt` (everything else is cut).
4. `vcut text <name> [--marks]`: **read the entire final script** and fix every splice that reads wrong.

Rules: the last complete take wins; drop everything between attempts ("okay", "wait", "let me say that again"). If
the last take is abandoned, garbled or factually wrong, keep an earlier good one and tell the user. Backtracks ("open
it it right here") → cut the repeated words only. Off-topic stretches (waiting, chatting, background audio) → cut.
Asides that were themselves re-taken are meant to stay. Lines abandoned and re-said differently → cut the first.
**Only cut, never reorder.** Word indices refer to `work/words.json`: re-transcribing changes them.
Pause targets live in `work/decisions.json` `settings` (`sentence_gap_to` 0.3, `comma_gap_to` 0.2, mid-sentence
pauses close to the natural gap); `gap_kinds` {word index: "sentence"|"comma"|"mid"} overrides one gap,
`force_keep` [[i0, i1]] protects words.

### Traps (check before building)
- **Stretched words hide retakes** (a word > 1.2 s, flagged `stretched`). Second opinion:
  `uv run --project pipeline python pipeline/tools/retx.py projects/<name>/work/asr16k.wav <start> <end> [lang]`.
  Fix `start`/`end` in `work/words.json`; add `"hard_start": true` when an attempt is glued to the previous one.
- **The aligner can put words on the wrong take.** Pause closing then deletes real speech. Before every build:
  `uv run --project pipeline python pipeline/tools/gapcheck.py projects/<name> -38 0.12 > projects/<name>/work/gaps.txt`, then
  `uv run --project pipeline python pipeline/tools/gapasr.py projects/<name>/work/asr16k.wav projects/<name>/work/gaps.txt`. Real
  words → `uv run --project pipeline python pipeline/tools/fixwords.py projects/<name> <i0> <i1> "w@start-end …"`
  (rewrites words.json, shifts keeps.txt indices; re-run `vcut analyze` before reading phrases again, and remap any
  layout/motion word anchors after the edit). "Thank you for watching" heard on noise is a hallucination.
- **The ASR drops periods at thinking pauses** or adds them mid-thought; edl.py treats a "sentence" followed by a
  continuation word (that, which, to…) as a comma pause. Measure kept silences:
  `uv run --project pipeline python pipeline/tools/joinsilence.py projects/<name>`.
- **Tight joins** (a word glued to a cut word) cut at the quietest 5 ms; list them for the user to hear.
- **Another language** spoken briefly is transcribed as English filler. Re-check with `retx.py … <lang>`.
- **VFR screen recordings lose time** while the screen is static, so it drifts late in long videos. Spot-check
  sync late in the video. If it drifts, write `projects/<name>/screen_sync.json`: `{"anchors": [[voice_t,
  screen_t, "note"], …]}` (window seconds), plus `"out_overrides": [[out_from_s, out_to_s, screen_t, "live"|"hold"]]`
  on the final timeline for click-through demos that must play continuously.
- **Mic dropouts**: the camera↔mic offset jumps mid-recording. Find the jump, build a repaired mic in `work/` (camera
  audio gain-matched into the gap), symlink it as `inputs/audio.wav`, keep the real file linked as `inputs/audio_raw.wav`.
- **Same line, different screen**: a re-take after the screen moved on may not match the slide. Check the screen.
- Things said on camera that later become false ("I'll delete this key later"): ask whether to blur and cut.

## Your cutting rules
<!-- CUSTOMIZE: how aggressive to cut, what to always keep or drop, pause lengths, filler words, how to treat asides and on-camera notes -->
_Empty. Filled in when you customize the editor._

## 4. Build
`vcut build <name>` = edl + render (camera at 1440p) + verify. VFR sources get a one-time CFR working copy; 720p
proxies go to `out/proxy/`. Verify must show equal frame counts and audio length. "Speech at join" warnings in a
noisy room are often mouse clicks: check the dB profile before acting. Both videos are cut from one `edl.json` on
one frame grid; never `-c copy` cut.

## 4b. QA pass (before the user sees any full video)
The cut transcript shares the first ASR pass's blind spots, so listen independently:
1. `vcut qa <name>` (background) → `out/qa.md`, `out/qa.json`, `out/qa_heard.md`. Spots: `diff` (heard ≠ kept),
   `repeat`, `pause`, `unclear`, `language`, `unheard`.
2. **Give every spot a verdict**: fix (keeps.txt / words.json, then `vcut keep` + `vcut build`), fine (with a
   reason: deliberate repeat, a demo loading, a click), or ask the user.
3. **Read all of `out/qa_heard.md`** like an editor: restarts, "wait / hold on / where is it", dead air, references
   to things not on screen or cut earlier, anything private said out loud.
4. Screen sync: contact sheets of `out/screen_cut.mp4` at 4–6 narrated moments, weighted to the second half.
5. Privacy: `uv run --project pipeline --with pyobjc-framework-Vision --with pyobjc-framework-Quartz python
   pipeline/tools/ocr_scan.py projects/<name>` (macOS) flags emails, keys, account pages. List them; blur what the user picks.
6. Re-run `vcut qa` after a rebuild. Keep the verdicts for the report.

## 5. Layout
`projects/<name>/out/layout.json` (times = cut-timeline seconds; compute them from `out/edl.json` joins and
`out/transcript_cut.json` words so switches land on cuts, and recompute after every rebuild):
- `card` {x, y, w, h, radius, faceX, top, zoom}: the face card (fractions of the frame; defaults in `Main.tsx`).
- `full` [{from, to, note}]: full-screen talking head. `punchIn` (e.g. 1.1): zoom on real jump cuts inside it.
- `images` [{from, to, src, note, push?{x, y, scale}}]: a still in place of the screen, face card kept.
- `zooms` [{from, to, x, y, scale, note, marks?[{x, y, w, h}]}]: push into a screen point (scale 1.4–2.2).
- `phones` [{src, from, to, srcStart, rate, srcDuration, side, zooms, statusBar}]: phone clips over the full head.
- `demos` [{src, from, to, srcStart, rate, srcDuration}]: a recording in place of the screen (not inside `full`).
- `blurs` [{from, to, x, y, w, h}]: frosted boxes over secrets. Render stills to confirm full coverage.
- `faceKeys` [{t, x}]: a moving face crop for long recordings.

Tools (run after the build, before the first draft):
- **Face card**: `uv run --no-project --with "opencv-python-headless==4.10.0.84" --with "numpy<2.3" python
  pipeline/tools/facecard.py projects/<name>` sizes the card to the empty strip of the screen recording (`--edge
  0.74` if the wallpaper isn't blue), centres the face, and checks it (`out/face_check.png`; exit 1 = not centred).
  If the speaker drifts, `pipeline/tools/facetrack.py projects/<name>` (same uv flags) → `out/face_track.json`;
  load it as `layout.faceKeys` and run facecard.py again. faceKeys projects render 4K with `render_chunks.sh`.
- **Auto-zooms** (a proposal): `uv run --project pipeline --with pyobjc-framework-Vision --with
  pyobjc-framework-Quartz --with "opencv-python-headless<4.12" python pipeline/tools/autozoom.py <name> [--from s
  --to s]` → `out/layout_autozoom.json` + `out/autozoom.md`. Copy only the zooms the user keeps into layout.json.
- Long scroll through a page → one tall image: `pipeline/tools/stitch_scroll.py` (for `images`).
- Preview: `npx remotion still Main ../projects/<name>/out/still.png --frame=N --props='{"project":"<name>"}'`;
  cut-only render: `npx remotion render Main ../projects/<name>/out/<name>_final.mp4 --props='{"project":"<name>"}'`.

## Your layouts
<!-- CUSTOMIZE: when to use full-screen talking head vs screen + face card, card position and size, punch-ins, zooms, intros/outros -->
_Empty. Filled in when you customize the editor._

## 5c. Long videos: parts
Split by chapter into parts of 30–45 min, each its own project (`<name>_p1`, `<name>_p2`…) sharing the full
project's words.json, so one part is reviewed while the next renders. After `vcut keep` of the full project and every
part and `vcut edl <name>`: `uv run --project pipeline python pipeline/tools/parts_split.py edges <name> <name>_p1
<name>_p2` (exact part edges), `vcut build` each part, then `parts_split.py <name> <name>_p1 <name>_p2` (moves layout
and motion into the parts, prints each part's `hybrid_render.py … --no-master --part '…'` command). Join the
`out/hybrid/joined.mov` files with an ffmpeg concat (`-c copy`, PCM) and master once with `vcut.master.master`.

## 6. Report
Original → cut length; decisions the user should know (takes swapped for content, asides kept, abrupt
transitions); tight joins with timestamps; which lines are full screen; the QA result ("checked and fixed", one line
per spot, plus what is left to judge); content mistakes with a recommended fix; hook material for /motion; questions.

## Adjusting later
Notes on a draft with chapter cards are on the final timeline (`at.py`); on a cut-only video, on the cut timeline
(`pipeline/tools/cut2src.py projects/<name> <cut_t>…`). Edit `keeps.txt`, `vcut keep` + `vcut build`, recompute the
layout, re-render. No re-transcription needed.

## Lessons learned
<!-- CUSTOMIZE: rules saved from review notes. When the user says "save this for next time", append a dated one-line rule here -->
_Empty. Filled in when you customize the editor._
