#!/bin/sh
# Requires the source-built diagnostic kernel and a running VDIN1 session.
set -eu
if [ "$#" -ne 1 ]; then
  echo 'Usage: capture-ready.sh unique_capture_name' >&2
  exit 2
fi
case "$1" in ''|*[!A-Za-z0-9_-]*) echo 'Use letters, digits, underscore or hyphen.' >&2; exit 2 ;; esac
attr=/sys/class/vdin/vdin1/attr
folder=/storage/e900-capture
final="$folder/$1.e9cap"
partial="$final.partial"
[ -w "$attr" ] || { echo 'VDIN diagnostic interface is unavailable.' >&2; exit 1; }
[ ! -e "$final" ] && [ ! -e "$partial" ] || { echo 'Capture name already exists; choose a new name.' >&2; exit 1; }
# Decoder/DI teardown can gate this shared clock after the session was started.
# Do not publish an old queued frame as a current playback observation.
if [ -w /sys/class/vpu/gate ]; then
  irq_count() {
    awk '$NF == "vdin1-irq" { n=0; for (i=2; i<=NF && $i ~ /^[0-9]+$/; i++) n+=$i; print n }' /proc/interrupts
  }
  before=$(irq_count)
  printf 'w 72 1\n' > /sys/class/vpu/gate
  sleep 0.2
  after=$(irq_count)
  [ -n "$before" ] && [ -n "$after" ] && [ "$after" -gt "$before" ] || {
    echo 'No fresh VDIN interrupt; refusing a potentially stale snapshot.' >&2
    exit 1
  }
fi
mkdir -p "$folder"
trap 'rm -f "$partial"' 0
trap 'exit 1' HUP INT TERM
printf 'capture_ready %s\n' "$partial" > "$attr"
mv "$partial" "$final"
# Continuous paired sampling validates/copies each packet immediately.
# Avoid an unrelated system-wide USB writeback stall in that mode.
if [ "${E900_CAPTURE_SKIP_SYNC:-0}" != 1 ]; then sync; fi
printf '%s\n' "$final"
