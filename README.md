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

> **Using it in a company of 4 or more people?** The videos are rendered with [Remotion](https://www.remotion.dev),
> which has its own license: free for individuals, companies of up to 3 people and non-profits, but larger companies
> need a [Remotion company license](https://www.remotion.dev/license). See [Licenses](#licenses).

## What you need
- [Claude Code](https://claude.com/claude-code)
- macOS, Windows or Linux. It configures itself for your chip (`vcut setup`): Apple Silicon, Nvidia, Intel and AMD
  GPUs are used when present, and everything also runs on the CPU (slower). Built on Apple Silicon Macs.
- [uv](https://docs.astral.sh/uv/) (Python 3.12), Node.js 18+, ffmpeg, git
  - macOS: `brew install uv node ffmpeg git`
  - Windows: `winget install astral-sh.uv OpenJS.NodeJS.LTS Gyan.FFmpeg Git.Git` (run the editor's commands in Git Bash)
  - Linux: ffmpeg, nodejs and git from your package manager, uv from docs.astral.sh/uv

## Install
```bash
git clone https://github.com/danbuica/ai-video-editor-template.git
cd ai-video-editor-template
uv run --project pipeline vcut setup     # installs the Python side, then detects your GPU / video encoder
npm --prefix remotion install
```
`vcut setup` writes `hardware.json` (this computer's encoder, decoder and where the speech models run) and prints what
it found. Run it again if you change GPU or ffmpeg.

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
- `hardware.json`: this computer's setup (git-ignored, written by `vcut setup`)

## Licenses
This template's own code is MIT licensed (see `LICENSE`). That covers this template only, not the tools it installs,
which keep their own licenses:

- **Remotion** (renders every video) is source-available under the [Remotion License](https://www.remotion.dev/license),
  not MIT. It's **free for individuals, for-profit companies with up to 3 employees, and non-profits**. A company with
  **4 or more people** needs a paid [Remotion company license](https://www.remotion.dev/license) once it uses the
  editor beyond evaluating it (for collaborations, the combined headcount counts). Using this template doesn't grant
  you a Remotion license: check that you're eligible, and read their current terms, since they can change.
- WhisperX, faster-whisper and the Whisper / wav2vec2 models have their own (permissive) licenses.
- Music and sound effects are yours to bring, under whatever license they come with.
