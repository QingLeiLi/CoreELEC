#!/bin/sh
# First source-built VDIN experiment: one start per boot, repeatable snapshots.
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run as root on the CoreELEC box.' >&2; exit 1; }
mode=$(tr -d '\r\n' < /sys/class/display/mode)
case "$mode" in
  1080p60hz) width=1920; height=1080; fps=60 ;;
  1080p50hz) width=1920; height=1080; fps=50 ;;
  720p60hz) width=1280; height=720; fps=60 ;;
  720p50hz) width=1280; height=720; fps=50 ;;
  *) echo "Unverified input mode: $mode" >&2; exit 1 ;;
esac
modprobe tvin_viuin
modprobe tvin_vdin gxlx2_capture=1
case "$(cat /sys/module/tvin_vdin/parameters/gxlx2_capture)" in
  Y|1) ;;
  *) echo 'VDIN was already loaded without opt-in. A fresh diagnostic boot/load is required.' >&2; exit 1 ;;
esac
attr=/sys/class/vdin/vdin1/attr
[ -w /sys/class/vdin/vdin0/attr ] && [ -w "$attr" ] || { echo 'Both VDIN instances must probe successfully; inspect dmesg.' >&2; exit 1; }
# TVIN_RGB444=0. Input timing stays at the current display mode; output is scaled.
printf 'conversion 640 360 0\n' > "$attr"
printf 'v4l2start viuin %s %s %s 0 0 0 0\n' "$width" "$height" "$fps" > "$attr"
mkdir -p /storage/e900-capture
printf 'boot_id=%s\ninput_mode=%s\nrequested_output=640x360 RGB444\n' "$(cat /proc/sys/kernel/random/boot_id)" "$mode" > /storage/e900-capture/session.txt
printf 'VDIN start returned success. Use e900-capture-ready.sh to verify a completed frame.\n'
