# AI Video Editor (template)

A video editor that Claude Code runs for you. Drop in your raw recordings and it:

- **syncs** your camera, screen recording and mic (by their audio)
- **transcribes** every word with timestamps (WhisperX)
- **cuts the retakes**: the last complete take wins, false starts and fillers go, long pauses get tightened
- **follows notes you say while filming** ("editor, zoom in on me right now")
- **lays it out**: screen recording with a face card, full-screen talking head where it matters, zooms, blurs
- adds **motion graphics, chapter cards, music and sound effects** (your own free library works)
- renders **low-res drafts** for your notes, then the **4K final**
- turns the same video into **Shorts, TikToks and Reels**

It's a template: the engine is complete, but the rules, style and graphics are empty, because your videos aren't
mine. You fill them in with one customization prompt, and the editor learns more from every round of notes.

## What you need
- [Claude Code](https://claude.com/claude-code)
- macOS on Apple Silicon (built and tested there; most of it runs elsewhere, but slower)
- [uv](https://docs.astral.sh/uv/) (Python 3.12), Node.js 18+, ffmpeg (`brew install uv node ffmpeg`)

## Install
```bash
git clone https://github.com/danbuica/ai-video-editor-template.git
cd ai-video-editor-template
uv sync --project pipeline
npm --prefix remotion install
```

## Try it on the built-in example
```bash
uv run --project pipeline python pipeline/tests/make_synthetic.py
```
That makes `projects/example`: a test video with planted retakes, a stutter, a filler and a thinking pause. Then open
Claude Code in this folder and say: `/cut example`. The first run downloads the speech models (a few GB).

## Make it yours
1. Get the **customization prompt** (free) from the Skool community:
   https://www.skool.com/automate-earn-with-ai-4633/about
2. Paste it into Claude Code in this folder and describe your videos: what you film, your style, your layouts,
   your music. It shows you example visuals and only builds them into the editor after you approve them.
3. Put your own music and sound effects in `projects/_assets/music` and `projects/_assets/sfx` (the YouTube Audio
   Library is a good free source), then run `uv run --project pipeline python pipeline/tools/assets.py sfx`.

Then point Claude at a folder of recordings: `/cut` for a full video, `/shorts` for vertical clips.

## How it fits together
- `pipeline/`: Python (`vcut` CLI): probe, sync, transcribe, find retakes, build a frame-exact edit list, render, check
- `remotion/`: [Remotion](https://www.remotion.dev) compositions: layout, graphics, chapter cards, music, shorts
- `.claude/skills/`: the `/cut`, `/motion` and `/shorts` guides Claude follows (their rule sections start empty)
- `CLAUDE.md`: the map of the system and every command
- `projects/`: your videos (git-ignored; originals are only ever symlinked, never modified)

## Licenses
This template is MIT licensed (see `LICENSE`). It builds on other projects with their own licenses, notably
**Remotion**, which is free for individuals and companies of up to 3 people; larger companies need a
[Remotion company license](https://www.remotion.dev/license). WhisperX, faster-whisper and the Whisper / wav2vec2
models have their own (permissive) licenses. Music and sound effects are yours to bring.
