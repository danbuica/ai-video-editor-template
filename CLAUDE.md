# AI video editor

An editing system that Claude Code runs: it syncs your recordings, cuts the retakes (the last complete take wins),
closes thinking pauses, lays the video out, adds motion graphics, music and sound effects, and renders the final in
Remotion. You film and give notes; Claude edits. Shorts for YouTube, TikTok and Reels come from the same system.

Skills: `/cut` (`.claude/skills/cut/SKILL.md`, the whole first pass), `/motion` (graphics, chapters, music, sound),
`/shorts` (vertical shorts, standalone or cut from a long video).

## Your editor
<!-- CUSTOMIZE: who makes the videos, what kind of videos, the files each video has (camera, screen recording, separate
mic…), language, where the recordings live, how drafts get reviewed. -->
_Empty. Filled in when you customize the editor._

The template assumes up to three files per video: **talking** (camera), **screen** (screen recording, often variable
frame rate and silent) and **audio** (a separate mic, the master audio when present). Any other set works: a
talking-head-only video uses the camera file as both talking and screen; tell Claude what you have.

**Never modify the original recordings.** Inputs are symlinks (`vcut link`). vcut refuses writes outside `projects/` and verifies the
originals' size+mtime before/after every command.

## Layout
```
pipeline/            Python 3.12 (uv). `vcut` CLI
  vcut/probe.py        describe inputs, auto-sync by audio (camera↔mic), manual sync.json for silent sources, shared window
  vcut/hw.py           this computer's hardware (`vcut setup` → hardware.json): video encoder/decoder, speech-model devices
  vcut/transcribe.py   WhisperX large-v3 (CPU int8 or CUDA, prompt + the video's names from names.txt) + wav2vec2
                       alignment (GPU when there is one) + recovery pass (no prompt; hallucination filter)
  vcut/analyze.py      phrases, pause kinds, retake candidates → candidates.md, decisions.json
  vcut/edl.py          decisions → frame-exact edl.json (joins in real silence) + transcript_cut.json + review.md
  vcut/render.py       numpy sample-accurate audio; chunked seek-based video; CFR copy for VFR sources;
                       720p draft proxies (out/proxy/)
  vcut/verify.py       frame counts, audio length, joins vs speech level, tight joins, optional ASR re-check
  vcut/qa.py           independent re-transcription of the cut → flags (diff, repeat, pause, unclear, language, unheard)
  vcut/housekeeping.py export next to the recordings, clean big media after a verified export
  tests/make_synthetic.py  synthetic project with planted retakes (`projects/example`, the regression test)
  tools/assets.py          your music + SFX library (projects/_assets/{music,sfx}) → sfx library.json, music beds
  tools/hybrid_render.py   fast 4K final: ffmpeg draws plain frames (screen + card), Remotion FinalSubset the rest, numpy
                           sound (hybrid_plan.py, hybrid_audio.py); render_chunks.sh = Remotion-only fallback (faceKeys)
  tools/autozoom.py        auto-zoom proposals on "click on X" / "right here" (OCR via vcut/ocr.py + pointer templates)
  tools/facecard.py        size the face card to the recording, frame + centre the face (facetrack.py: follow it)
  tools/parts_split.py     long videos: split a project's layout/motion into part projects (music offset per part)
  tools/at.py, cut2src.py, fixwords.py, retx.py, joincheck.py, gapcheck.py, gapasr.py, joinsilence.py, ocr_scan.py,
  stitch_scroll.py         review helpers (docstring at the top of each)
remotion/            Remotion 4. publicDir = ../projects → staticFile("<project>/out/…")
  src/Main.tsx         layout (screen + face card, full-screen ranges, images, zooms, phones, blurs, punch-in on jump cuts)
  src/Final.tsx        Main + chapter cards + ducked music bed; MotionReel.tsx previews every graphic for approval
  src/motion/          theme.ts (your look), graphics/ (your graphics library, index.ts = registry), chapters.tsx
                       (chapter card styles), types.ts (motion.json), MotionLayer.tsx (draws graphics + SFX)
  src/Short.tsx        vertical short: visual on top, face below, captions, end card
  src/ShortV2.tsx      vertical short that switches full / split / face; content per short in src/shorts/
  src/CutReview.tsx    review view: both cut files + captions + join timeline
  src/FinalSubset.tsx  only the Final frames ffmpeg can't draw (for hybrid_render.py)
projects/<name>/     per video (git-ignored): inputs/ (symlinks), sync.json, names.txt, keeps.txt, work/, out/
projects/_assets/    your own music/ and sfx/ (git-ignored)
```

## Commands (from repo root, `V="uv run --project pipeline vcut"`)
- `$V setup`: once per computer, right after install (detects the GPU / video encoder → `hardware.json`). If
  `hardware.json` is missing, run it before anything else.
- `$V new <name>`, then `$V link <name> talking|screen|audio "<path to the recording>"` (a symlink, never a copy)
- `$V prepare <name> [--until 600] [--language en]`: probe + transcribe + analyze
- `$V phrases <name> [from] [to] [--indexed]`: compact transcript for choosing takes
- `$V keep <name> projects/<name>/keeps.txt`: apply the explicit keep-list → decisions.json
- `$V text <name>`: final script under the current decisions (read it all)
- `$V build <name>`: edl + render (camera at 1440p) + verify
- `$V qa <name>`: after build, listen to the cut independently → out/qa.md + qa_heard.md (AI reviews every spot)
- `$V transcript <name>`, `$V chapters <name>`: final-timeline transcript and chapter timestamps
- `$V export <name>`: copy the final next to the recordings (`<recordings>/export/`, new files only)
- `$V clean <name> [--yes]`: delete big regenerable media after a verified export (dry run by default). Run `--yes`
  only after the user has watched the exported file and said it's safe to delete.
- 720p draft: `uv run --project pipeline --with "opencv-python-headless<4.12" python pipeline/tools/hybrid_render.py <name> --draft`
  → `out/<name>_draft_720p.mp4` (from the 720p proxies; keeps the computer awake while it runs)
- 4K final: the same without `--draft` → `out/<name>_final_4k.mp4` (resumable; projects with faceKeys:
  `bash pipeline/tools/render_chunks.sh <name>`). Never use proxies for the final.
- Remotion studio: `npm --prefix remotion run dev`, or render one composition:
  `cd remotion && npx remotion render Final ../projects/<name>/out/<name>.mp4 --props='{"project":"<name>"}'`

## Invariants
- Both videos are cut from **one** edl.json by frame index on one CFR grid → identical frame counts. Never `-c copy` cut.
- Joins sit in the pause found from the loudness envelope near each word edge (noise in the middle of a pause is
  ignored). Tight joins (word glued to a cut word) go at the quietest 5 ms; that segment's audio may slide ≤ ½ frame.
- Mid-sentence joins close to the speaker's natural word gap; sentence pauses → 0.3 s; comma → 0.2 s.
- Word indices refer to `work/words.json`. Re-transcribing changes them, so map old keep-lists by time.
- Graphics are anchored to words (`{"w": <index>}`), so they follow the cut when it changes.
- Drafts are 720p until the user approves the cut; the 4K final renders only after that.
- ffmpeg gotchas: muxing audio in the same command as a heavy video filter crawls (mux separately); a select
  expression with hundreds of `between()` terms fails to parse (render in chunks).

## Machine notes
Runs on macOS, Windows and Linux. `vcut setup` tests what this computer has and writes `hardware.json` (git-ignored);
`$V setup` again after a GPU or ffmpeg change, `python -m vcut.hw` (with `uv run --project pipeline`) shows it.
- Apple Silicon Mac: VideoToolbox encode/decode, alignment on the GPU (MPS), recovery pass on the GPU (mlx-whisper).
  85 min of footage ≈ 25 min of transcription on an M-series Pro.
- Nvidia GPU: NVENC encode, CUDA decode, and Whisper on the GPU when CUDA works for it (setup checks; it needs a
  CUDA build of torch and the cuBLAS/cuDNN libraries, otherwise transcription stays on the CPU).
- Intel / AMD GPU: QuickSync / AMF encode. No usable GPU: x264 on the CPU (slower, same result).
- WhisperX's main pass on the CPU: int8, ~2.5× realtime on a fast machine.
- The 4K final (hybrid_render.py) draws plain frames with ffmpeg (~65 fps vs Remotion's ~6) and encodes with
  VideoToolbox on a Mac, x264 elsewhere (matches Remotion's colours exactly). Remotion tabs come from hardware.json.
- OCR (autozoom.py, ocr_scan.py): macOS Vision on a Mac, RapidOCR elsewhere (`--with rapidocr-onnxruntime`).
- Windows: run commands in Git Bash (Claude Code's shell there). Symlinks need Developer Mode (setup warns).
- Long commands (prepare, build, qa, the renders) keep the computer awake by themselves.
Other languages: pass `--language`, and translate the disfluent prompt, fillers and retake cues in
`vcut/transcribe.py` / `vcut/analyze.py` / `vcut/qa.py` (they are English).
<!-- CUSTOMIZE: your machine (chip, RAM), where recordings live, anything setup got wrong for it. -->
