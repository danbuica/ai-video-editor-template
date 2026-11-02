"""joincheck.py <project_dir> <src_i> [src_i …] — re-transcribe the cut audio around each join that lands right
before word src_i (faster-whisper, fresh ears) and print heard vs expected. Run after every rebuild on the joins you
changed; cheaper than a full `vcut qa`. Deps: uv run --project pipeline python pipeline/tools/joincheck.py …"""
import json, subprocess, sys, tempfile
from pathlib import Path
import soundfile as sf
from faster_whisper import WhisperModel
pdir = Path(sys.argv[1]); after = {int(x) for x in sys.argv[2:]}
wav = Path(tempfile.gettempdir()) / f"joincheck_{pdir.name}.wav"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(pdir / "work/cut_master.wav"), "-ac", "1", "-ar", "16000", str(wav)], check=True)
cw = json.loads((pdir / "out/transcript_cut.json").read_text())["words"]
m = WhisperModel("large-v3", device="cpu", compute_type="int8", cpu_threads=8)
for k, w in enumerate(cw):
    if w["src_i"] in after and k > 0:
        a = max(0, cw[k - 1]["start"] - 2.5); b = w["end"] + 2.5
        x, _ = sf.read(str(wav), start=int(a * 16000), stop=int(b * 16000), dtype="float32")
        segs, _ = m.transcribe(x, language="en", vad_filter=False, condition_on_previous_text=False)
        print(f"[{w['src_i']}] cut {w['start']:.1f}\n  heard: {' '.join(s.text.strip() for s in segs)}\n"
              f"  text : {' '.join(c['w'] for c in cw if a <= c['start'] <= b)}")
