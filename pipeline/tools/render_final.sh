#!/bin/zsh
# Resumable 4K final: Remotion "Final" in muted video chunks + one audio pass, joined, then mastered.
# A crash only loses the chunk in flight; re-run the same command and finished chunks are skipped.
# (A single 70k-frame render at concurrency 10 can swap and die on one hung frame.)
#
#   pipeline/tools/render_final.sh <project> [chunk=10000] [concurrency=6] [motionFile=motion.json]
# Run from the repo root. Output: projects/<project>/out/<project>_final_4k.mp4
set -e
P=$1; CHUNK=${2:-10000}; CONC=${3:-6}; MOTION=${4:-motion.json}
ROOT=$PWD; OUT=$ROOT/projects/$P/out; PARTS=$OUT/final_parts
PROPS="{\"project\":\"$P\",\"motionFile\":\"$MOTION\"}"
mkdir -p $PARTS
cd $ROOT/remotion

TOTAL=$(npx remotion compositions --props="$PROPS" 2>/dev/null | awk '$1=="Final"{print $4}')
[[ -z $TOTAL ]] && { echo "could not read Final's duration"; exit 1; }
echo "[$(date +%T)] $P: $TOTAL frames, chunks of $CHUNK, concurrency $CONC"

: > $PARTS/list.txt
for ((a=0; a<TOTAL; a+=CHUNK)); do
  b=$(( a+CHUNK-1 < TOTAL-1 ? a+CHUNK-1 : TOTAL-1 ))
  f=$PARTS/v_$(printf %06d $a).mp4
  echo "file '$f'" >> $PARTS/list.txt
  [[ -s $f ]] && { echo "[$(date +%T)] chunk $a-$b already done"; continue; }
  echo "[$(date +%T)] chunk $a-$b"
  npx remotion render Final $PARTS/tmp.mp4 --frames=$a-$b --muted --scale=2 --jpeg-quality=100 \
    --concurrency=$CONC --timeout=120000 --hardware-acceleration=required --video-bitrate=60M --props="$PROPS"
  mv $PARTS/tmp.mp4 $f
done

if [[ ! -s $PARTS/audio.wav ]]; then
  echo "[$(date +%T)] audio"
  npx remotion render Final $PARTS/audio_tmp.wav --codec=wav --props="$PROPS"
  mv $PARTS/audio_tmp.wav $PARTS/audio.wav
fi

echo "[$(date +%T)] join"
ffmpeg -v error -y -f concat -safe 0 -i $PARTS/list.txt -i $PARTS/audio.wav -map 0:v -map 1:a -c:v copy -c:a pcm_s16le \
  $OUT/final_raw.mov
echo "[$(date +%T)] master"
cd $ROOT
uv run --project pipeline python -c "from pathlib import Path; from vcut.master import master; \
print(master(Path('$OUT/final_raw.mov'), Path('$OUT/${P}_final_4k.mp4')))"
ffprobe -v error -count_packets -select_streams v:0 -show_entries stream=width,height,nb_read_packets:format=duration \
  -of compact $OUT/${P}_final_4k.mp4
echo "[$(date +%T)] done"
