---
name: motion
description: Add motion graphics, chapter cards, background music and sound effects to a cut video, render a fast 720p draft for review, then the 4K final after approval. Use when the user says "/motion", "add motion graphics", "add the graphics", "chapters", "add music", "sound effects", "render the final", or asks to change graphics, music or chapters on an existing project. Normally runs inside the /cut one-pass flow (no proposal round); propose first only when the user asks for /motion on its own.
---

# /motion: graphics, chapters, music, sound

Runs after `/cut`. Needs `projects/<name>/out/{edl.json, transcript_cut.json, layout.json, talking_cut.mp4,
screen_cut.mp4}`. Everything goes into `projects/<name>/out/motion.json`; Remotion's `Final` composition draws it.
`vcut …` = `uv run --project pipeline vcut …` from the repo root; `npx remotion …` runs from `remotion/`.

How the engine places graphics (`Main.tsx`, `MotionLayer.tsx`):
- Graphics draw **only while the talking head is full screen**: inside a `layout.json` `full` range, or on an
  item with `"fullscreen": true` (which makes its own full-screen range). Never over the screen-recording layout;
  screen moments use `layout.json` `zooms` / `images` instead.
- `side: "left" | "right" | "center"` pushes the head away from the graphic and shades that side.
- Types starting with `scene-` are full-frame scenes: the head goes full screen, blurred underneath. `"card": true`
  keeps the face card on top. A scene must finish before its full-screen range ends.
- A `type` that is not registered shows a red "no graphic …" label in the draft, so a gap is never silent.

## Your style
<!-- CUSTOMIZE: the look (colours, fonts, glass/flat, light/dark), energy and pace, how often graphics appear, what never to do -->
_Empty. Filled in when you customize the editor._

The look's code lives in `remotion/src/motion/theme.ts` (font, `ACCENT`, `ACCENT2`, `ACCENT_GRAD`, springs,
`enterStyle`, `exitProgress`). Every graphic, chapter card and caption reads from it; a render can override the accent
with the `accent` / `accent2` props.

## motion.json
```json
{ "items": [ { "id": "g1", "type": "text-pop", "side": "left", "fullscreen": true,
               "from": {"w": 120}, "to": {"w": 140, "end": true},
               "sfx": [{"name": "whoosh", "at": {"w": 120}, "hit": true, "vol": 1}], "note": "…", "...": "the graphic's own fields" } ],
  "chapters": [{ "at": {"w": 300}, "number": 1, "title": "Setup", "sub": "optional" }],
  "chapterSeconds": 2, "chapterStyle": "default", "chapterSfx": "whoosh",
  "music": { "file": "<name>/out/music_bed.wav", "lufs": -14.2, "gainDb": 0, "label": "track" },
  "sfxVolume": 0.1 }
```
**Word anchors.** Every time is a `TimeRef`: `{"w": <word index in work/words.json>, "pad": <seconds>, "end": true?}`
= that word's start (or end) + pad on the current cut. A cut word resolves to the next kept word. Anchors survive
re-cuts; a plain number (cut seconds) does not, so use anchors. Any field anywhere in an item can be a TimeRef.
Trap: an object with a numeric `w` is read as an anchor, so never name a width `w` in item data (a box with
`x, y, w, h` is left alone). After `fixwords.py` changes word indices, remap the anchors.

## Your graphics library
Each `type` the editor knows, when to use it, and its fields. The template ships two **examples, replace them**:
- `text-pop` (`motion/graphics/TextPop.tsx`): lines of text popping in beside the head. Fields: `side`,
  `lines: [{text, at: TimeRef, accent?: bool}]`. Needs `fullscreen: true` or a `full` range.
- `scene-title` (`motion/graphics/SceneTitle.tsx`): a full-frame title. Fields: `title`, `sub?`, `at?: TimeRef`
  (when the title lands; default `from`).

<!-- CUSTOMIZE: one entry per graphic type: name, when to use it (which kind of line), its motion.json fields, its sounds -->
_Empty. Filled in when you customize the editor._

### Adding a new graphic
1. One component per file in `remotion/src/motion/graphics/<Name>.tsx`: `React.FC<{ item: MotionItem }>`. `item`
   arrives with every TimeRef resolved to cut seconds; animate with `useCurrentFrame()` / fps, fade out with
   `exitProgress` before `item.to`. Read colours and fonts from `theme.ts`. Use the `scene-` prefix for full frame.
2. Register it in `GRAPHICS` in `remotion/src/motion/graphics/index.ts`.
3. Document it in "Your graphics library" above (when to use it + fields), so the next video uses it right.
4. Preview it alone (MotionReel, below) and check stills at its key beats.
Design: list the line's beats, give each one an element and a cue on the word that says it, one sound per beat.
Keep text short, inside the frame and away from the face.

## Chapter cards
`chapters` insert a card of `chapterSeconds` (default 2) before each chapter; the backdrop is the chapter's first
frame. Styles live in `CHAPTER_CARDS` in `remotion/src/motion/chapters.tsx` (only `default` ships). A new style is a
`React.FC<ChapterCardProps>` ({number, title, sub, durationInFrames, backdrop}) added to `CHAPTER_CARDS` and picked
with `chapterStyle`. Chapters come from what was actually recorded (the transcript), not from a script.
`vcut chapters <name>` writes `out/youtube_chapters.txt` with final-video times and checks YouTube's rules (≥ 3
chapters, each ≥ 10 s). Don't put a card right before a graphic that says the same thing.

## Your hook
<!-- CUSTOMIZE: what the first ~30 s should do (moving UI, a post reveal, a result first, a question), what the opener must never be -->
_Empty. Filled in when you customize the editor._

The opening seconds play as the hover preview, so they should move. Tools: screen `zooms` and `images` in layout.json
(a screenshot of a post or page in place of the screen), full-frame scenes, a result shown first. Prefer real
artefacts from the video (a frame of `out/screen_cut.mp4`, a page screenshot saved to `out/`) over drawn imitations.

## Music and sound
Bring your own free library (e.g. the YouTube Audio Library): music in `projects/_assets/music/`, sound effects in
`projects/_assets/sfx/` (one file per sound, name = the file name without extension).
- `uv run --project pipeline python pipeline/tools/assets.py sfx` → a .wav per sound + `library.json` (length,
  `peak_at` so `"hit": true` lands the peak on the cue, `trim_db` that evens out loud and quiet samples). Re-run after
  adding sounds.
- `uv run --project pipeline python pipeline/tools/assets.py music <name> <track> [--skip-intro 8]` → a seamless
  bed `out/music_bed.wav` and the `music` entry to paste into motion.json. `Final` normalises it and ducks it under
  the voice; `gainDb` trims it per video.
- `sfxVolume` scales every SFX (−3 dB = ×0.708); `vol` scales one. Repetitive or harsh sounds want less, airy ones more.
- Every render is mastered to −14 LUFS / −1 dBTP (`vcut.master.master`).

<!-- CUSTOMIZE: which tracks or genres, music level (gainDb), sfxVolume, which sound for which beat, when no music -->
_Empty. Filled in when you customize the editor._

## Workflow
**Default: inside the /cut one-pass flow.** Skip steps 1–3: go from the cut straight to `motion.json`, stills and the
720p draft; the review round (notes → draft 2 + `out/changes_v2.md`) is in /cut. Use steps 1–3 only when the user
asks for /motion on its own or for a proposal.
1. **Propose**: the hook, then a table (id, time, the line, what moves, sound), chapters, music options. Write it to
   `out/motion_proposal.json` (same format as motion.json).
2. **Preview reel** (each item in context, labelled): `cd remotion && npx remotion render MotionReel
   ../projects/<name>/out/motion_preview.mp4 --props='{"project":"<name>","motionFile":"motion_proposal.json","proxy":true}'`
   (`"only": ["g1"]` for one item). Stills: `npx remotion still Main ../projects/<name>/out/still.png --frame=N
   --scale=0.5 --props='{"project":"<name>","motionFile":"motion_proposal.json"}'` (cut-timeline frames). Look for text off the frame, overlaps with the next item, beats that
   land after the layout switched back.
3. The user keeps/drops/changes → `out/motion.json`.
4. **720p draft**: `uv run --project pipeline --with "opencv-python-headless<4.12" python pipeline/tools/hybrid_render.py
   <name> --draft > projects/<name>/out/draft_render.log 2>&1` → `out/<name>_draft_720p.mp4` (from the 720p proxies;
   missing? `vcut proxy <name>`). Re-running notices what changed. Projects with `faceKeys` are refused: render
   `npx remotion render Final ../projects/<name>/out/draft_raw.mp4 --scale=0.6666666666666666 --concurrency=6
   --props='{"project":"<name>","motionFile":"motion.json","proxy":true}'`, then master it: `uv run --project pipeline
   python -c "from pathlib import Path; from vcut.master import master; master(Path('projects/<name>/out/draft_raw.mp4'),
   Path('projects/<name>/out/<name>_draft_720p.mp4'))"`.
5. **4K final only after the user approves the draft** (it runs a while; let them pick the time). Late volume notes
   go straight into motion.json, no new draft. One background command, logged to `out/final_render.log`:
   `vcut render <name> --only talking --talking-height 0` (camera at source resolution), then
   `caffeinate -is uv run --project pipeline --with "opencv-python-headless<4.12" python pipeline/tools/hybrid_render.py
   <name>` → `out/<name>_final_4k.mp4` (ffmpeg draws plain screen + card frames, Remotion `FinalSubset` the rest;
   resumable: re-run after a crash). `faceKeys` projects: `caffeinate -is pipeline/tools/render_chunks.sh <name>`.
   Never use proxies for the final; never render a long final in one Remotion piece. Check duration = draft
   duration and a few full-res stills.
6. **Export**: `vcut export <name>` → `<recordings folder>/export/` (new files only, verified).
7. **Clean only after the user has watched the export and says it's safe**: `vcut clean <name>` (dry run), then
   `--yes`. It keeps the small edit files and never touches `projects/_assets`. Also empty your scratchpad.
8. Deliver `out/youtube_chapters.txt` with the final.

## Lessons learned
<!-- CUSTOMIZE: rules saved from review notes. When the user says "save this for next time", append a dated one-line rule here -->
_Empty. Filled in when you customize the editor._
