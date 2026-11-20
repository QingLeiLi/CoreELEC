#!/bin/sh
# Run while the H264 sample is already playing through amcodec.
set -eu
parameter=/sys/module/amvideo/parameters/gxlx2_stage_samples
[ -w "$parameter" ] || {
  echo 'This kernel has no display-stage hooks; build the updated decoder profile.' >&2
  exit 1
}
output=/storage/e900-display-stages
mkdir -p "$output"
boot_id=$(cat /proc/sys/kernel/random/boot_id)
run="$output/$boot_id-$(date +%s)"
mkdir "$run"
trap 'printf "0\n" > "$parameter"' EXIT
cat /proc/cmdline > "$run/cmdline.txt"
cat /sys/class/vfm/map > "$run/vfm.txt"
cat /sys/class/vdec/vdec_status > "$run/decoder-before.txt"
grep -q 'ammvdec_h264' "$run/decoder-before.txt" || {
  echo 'Start the H264 sample with amcodec before collecting stages.' >&2
  exit 1
}
for batch in 1 2 3 4; do
  printf '8\n' > "$parameter"
  sleep 1
  cat "$parameter" > "$run/budget-$batch.txt"
  sleep 1
done
cat /sys/class/vdec/vdec_status > "$run/decoder-after.txt"
cat /sys/class/video/video_state > "$run/video-state.txt"
cat /proc/interrupts > "$run/interrupts.txt"
dmesg > "$run/dmesg.txt"
grep 'e900-stage' "$run/dmesg.txt" > "$run/stages.txt" || :
sync
printf 'Display-stage evidence: %s\n' "$run"
