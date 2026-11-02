#!/bin/zsh
# Resumable 4K final in chunks, sound included: each chunk is Remotion "Final" with the hardware h264 encoder
# (same as the one-shot render) and uncompressed PCM audio in a .mov, so chunks join sample-exact with no extra
# audio pass. A failed chunk is retried once. Then the join is mastered once to AAC.
# Re-run the same command after a crash: finished chunks are skipped.
#
#   pipeline/tools/render_chunks.sh <project> [chunk=4000] [concurrency=10] [motionFile=motion.json] [out=<project>_final_4k.mp4]
# Extra Remotion flags via REMOTION_EXTRA, e.g. REMOTION_EXTRA="--offthreadvideo-cache-size-in-bytes=2000000000".
# Run from the repo root.
set -e
P=$1; CHUNK=${2:-4000}; CONC=${3:-10}; MOTION=${4:-motion.json}; NAME=${5:-${P}_final_4k.mp4}
ROOT=$PWD; OUT=$ROOT/projects/$P/out; PARTS=$OUT/chunks
PROPS="{\"project\":\"$P\",\"motionFile\":\"$MOTION\"}"
mkdir -p $PARTS
cd $ROOT/remotion

TOTAL=$(npx remotion compositions --props="$PROPS" 2>/dev/null | awk '$1=="Final"{print $4}')
[[ -z $TOTAL ]] && { echo "could not read Final's duration"; exit 1; }
echo "[$(date +%T)] $P: $TOTAL frames, chunks of $CHUNK, concurrency $CONC"

render_chunk() {
  npx remotion render Final $PARTS/tmp.mov --frames=$1-$2 --codec=h264 --audio-codec=pcm-16 \
    --scale=2 --jpeg-quality=100 --concurrency=$CONC --timeout=120000 --hardware-acceleration=required \
    --video-bitrate=60M ${=REMOTION_EXTRA} --props="$PROPS"
}

: > $PARTS/list.txt
for ((a=0; a<TOTAL; a+=CHUNK)); do
  b=$(( a+CHUNK-1 < TOTAL-1 ? a+CHUNK-1 : TOTAL-1 ))
  f=$PARTS/c_$(printf %06d $a).mov
  echo "file '$f'" >> $PARTS/list.txt
  [[ -s $f ]] && { echo "[$(date +%T)] chunk $a-$b already done"; continue; }
  echo "[$(date +%T)] chunk $a-$b"
  if ! render_chunk $a $b; then
    echo "[$(date +%T)] chunk $a-$b failed, retrying once"
    pkill -f "remotion/node_modules/.remotion/chrome-headless-shell" || true
    render_chunk $a $b
  fi
  pkill -f "remotion/node_modules/.remotion/chrome-headless-shell" || true
  mv $PARTS/tmp.mov $f
done

echo "[$(date +%T)] join"
ffmpeg -v error -y -f concat -safe 0 -i $PARTS/list.txt -c copy $OUT/chunks_joined.mov
echo "[$(date +%T)] master"
cd $ROOT
uv run --project pipeline python -c "from pathlib import Path; from vcut.master import master; \
print(master(Path('$OUT/chunks_joined.mov'), Path('$OUT/$NAME')))"
echo "[$(date +%T)] done"
