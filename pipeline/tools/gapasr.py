import sys, re, soundfile as sf
from faster_whisper import WhisperModel
wav, listing = sys.argv[1], sys.argv[2]
m = WhisperModel("large-v3", device="cpu", compute_type="int8", cpu_threads=10)
for line in open(listing):
    mm = re.match(r"(\d+)->(\d+) ([\d.]+)-([\d.]+)", line)
    if not mm: continue
    a, b = float(mm.group(3)) + 0.05, float(mm.group(4)) - 0.05
    x, sr = sf.read(wav, start=int(a * 16000), stop=int(b * 16000), dtype="float32")
    segs, _ = m.transcribe(x, language="en", word_timestamps=True, vad_filter=True, condition_on_previous_text=False)
    words = [f"{w.word.strip()}@{a + w.start:.2f}-{a + w.end:.2f}({w.probability:.2f})" for s in segs for w in s.words]
    print(line.strip()[:60], "=>", " ".join(words) or "-", flush=True)
