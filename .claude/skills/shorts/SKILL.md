---
name: shorts
description: Make vertical shorts (1080x1920) for YouTube Shorts, TikTok and Instagram Reels — from a standalone shorts recording (one camera + mic file holding several shorts, with retakes) or as clips cut from a finished long video using its transcript. Captions, face and visual panels, music and sound effects, one version per platform. Use when the user says "/shorts", "shorts", "make a reel", "do short 3", "shorts from this video", or points at a shorts recording.
---

# /shorts

Shorts reuse the /cut engine (sync, transcript, keep-list, cut) and render with one of two Remotion compositions.
`vcut …` = `uv run --project pipeline vcut …` from the repo root; `npx remotion …` runs from `remotion/`.

Two kinds of input:
- **A shorts recording**: one camera (+ mic) file holding several shorts, each with retakes and spoken notes
  ("Editor, starting short number two"). One project for the recording (`vcut new`, `vcut link` the camera as
  `talking` **and** `screen`, the mic as `audio`, `vcut prepare`). Then one project per short (`<rec>_s1`, `<rec>_s2`…)
  with the same `inputs/` symlinks and a copy of the recording project's `work/`, its own `keeps.txt` and cut.
  **The recording decides**: the last complete take of each line, only what was said.
- **A finished long video**: segments of its `out/transcript_cut.json` (cut-timeline seconds) in that project.
  Only lines already said; trimming a leading "Now," is fine, inventing words is not.

## Your shorts style
<!-- CUSTOMIZE: which composition (two-panel Short or switching ShortV2), shot length and pacing, captions look, how a short opens, face grading -->
_Empty. Filled in when you customize the editor._

## The two compositions
- **`Short`** (`remotion/src/Short.tsx`): two fixed panels, the visual on top (1080x1080, a crop of a 16:9 source)
  and the face below (1080x840), word captions at the seam. Props: `segments`, `top` [{from, to, mode: "crop"|"fit",
  x, y, w}], `topSrc` (default `out/screen_cut.mp4`) or `topImage`, `face` {x, y, w}, `full` [{from, to}] for
  full-screen face ranges + `fullFace`, `fullTitle` (`*word*` = accent), `endCardTop`, `accent`.
- **`ShortV2`** (`remotion/src/ShortV2.tsx`): the layout switches between `full` (the visual alone), `split` (visual
  on top 1080x960, face below) and `face` (full-screen punch-in), with 1–3 word pill captions. Props: `segments`,
  `content` (a key of `SHORTS`), `shots` (overrides the content's shot list), `faceSplit` / `faceFull` {x, y, w}.

Shared props: `project`, `segments` [{from, to}] (cut seconds, played back to back), **`audioSrc`** (the voice, e.g.
`work/cut_master.wav`; without it the short is silent), `faceSrc` (default `out/talking_cut.mp4`), `fixes`
({"Cloud": "Claude"} for every occurrence, {"#<src_i>": "…"} for one word), `variant` ("yt" | "ig"), `endCard`
(text) + `endSeconds`, `music` {file, lufs, gainDb}, `sfx` [{name, w | at, pad, vol, hit}], `sfxVolume`.

### New shorts content (ShortV2)
A content module `remotion/src/shorts/<id>.tsx` exports `shots(variant)` (cut-time ranges → `"full" | "split" |
"face"`) and a `Visual` component that draws the visual for any box (`box` {w, h}, `layout`, `t` = cut seconds,
`words`, `variant`; it is also called during `face` shots, so it can draw a badge there). Register it in `SHORTS` in
`remotion/src/shorts/index.ts`. `example` (`shorts/example.tsx`) shows the cut screen recording; real shorts usually
show footage of the thing talked about, stills, or drawn scenes. Document each content type you keep here.

## 1. Cut the short
1. `keeps.txt` with the last complete take of each line (`vcut phrases <proj> --indexed`), all endings at the end
   (one per platform, e.g. a comment-keyword line and a "watch the full video" line).
2. `vcut keep <proj> projects/<proj>/keeps.txt`, `vcut text <proj>` (read it), `vcut build <proj> --talking-height 0`.
3. A word stretched over a long silence keeps the pause in the cut: check the envelope, fix with
   `pipeline/tools/fixwords.py`, rebuild. `pipeline/tools/joincheck.py projects/<proj> <src_i…>` on every join.
4. Segments per version: each platform's version ends on its own ending line.

## 2. Footage
Decide the visuals per short and show the user the plan before recording anything new. Prefer the original files
(images, PDFs, real app screens) over screen captures of them; text must never be cut at a panel edge. Convert
clips to CFR H.264 in `out/` (VFR/HEVC decodes badly in Remotion).

## 3. Spec and stills
One spec per version: `projects/<proj>/shorts/<id>_<variant>.json`, e.g.
```json
{"project": "<proj>", "content": "example", "variant": "yt",
 "segments": [{"from": 0, "to": 27.0}, {"from": 29.36, "to": 32.3}],
 "audioSrc": "work/cut_master.wav", "fixes": {"#1748": "3D"},
 "music": {"file": "<proj>/out/music_bed.wav", "lufs": -14.2, "gainDb": 0},
 "sfxVolume": 0.1, "sfx": [{"name": "whoosh", "w": 1702, "hit": true}],
 "endCard": "Watch the full video", "endSeconds": 2}
```
Music bed: `uv run --project pipeline python pipeline/tools/assets.py music <proj> <track>`. Stills at every shot
change: `npx remotion still ShortV2 ../projects/<proj>/out/shorts/still.png --frame=N --scale=0.3
--props=../projects/<proj>/shorts/<spec>.json`. Look for text cut at edges, crops that miss the subject, captions
colliding with the end card, anything over the face.

## 4. Render and deliver
1. `npx remotion render ShortV2 ../projects/<proj>/out/shorts/<id>_<variant>_raw.mp4
   --props=../projects/<proj>/shorts/<id>_<variant>.json --concurrency=6 --crf=16` (or `Short`), then master
   to −14 LUFS: `uv run --project pipeline python -c "from pathlib import Path; from vcut.master import master;
   master(Path('projects/<proj>/out/shorts/<id>_<variant>_raw.mp4'), Path('projects/<proj>/out/shorts/<id>_<variant>.mp4'))"`,
   then delete the raw.
2. Check 1080x1920, duration = sum of segments, loudness, frames at every beat. The user reviews one version until
   they say final; then render the other platforms and check their endings.
3. `vcut export <proj> --src projects/<proj>/out/shorts/<file>.mp4` for each final (new files only).

## Platforms
<!-- CUSTOMIZE: which platforms, the variant per platform (end card, arrow to the related video, comment keyword, CTA), caption and hashtag rules, naming of the delivered files -->
_Empty. Filled in when you customize the editor._

`variant: "yt"` draws the end card with an arrow toward YouTube's related-video link; `"ig"` drops the arrow (put a
comment keyword or other CTA in `endCard` or in the content's `Visual`). Keep CTAs off the face.

## Lessons learned
<!-- CUSTOMIZE: rules saved from review notes. When the user says "save this for next time", append a dated one-line rule here -->
_Empty. Filled in when you customize the editor._
