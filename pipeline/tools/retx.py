"""retx.py <wav16k> <start_s> <end_s> [lang] — faster-whisper second opinion with word times (absolute)."""
import sys, soundfile as sf
from faster_whisper import WhisperModel
wav, a, b = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
lang = sys.argv[4] if len(sys.argv) > 4 else "en"
x, sr = sf.read(wav, start=int(a * 16000), stop=int(b * 16000), dtype="float32")
m = WhisperModel("large-v3", device="cpu", compute_type="int8", cpu_threads=8)
segs, _ = m.transcribe(x, language=lang, word_timestamps=True, vad_filter=False, condition_on_previous_text=False)
for s in segs:
    print(" ".join(f"{w.word.strip()}@{a + w.start:.2f}-{a + w.end:.2f}" for w in s.words))
