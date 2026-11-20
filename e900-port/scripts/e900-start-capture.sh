#!/bin/sh
# First source-built VDIN experiment: one start per boot, repeatable snapshots.
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run as root on the CoreELEC box.' >&2; exit 1; }
folder=/storage/e900-capture
mkdir -p "$folder"
# Persist the last boundary before each first-time hardware operation. A hard
# lock cannot return a shell error; this record survives the next power cycle.
phase() {
  printf 'boot_id=%s\nphase=%s\n' "$(cat /proc/sys/kernel/random/boot_id)" "$1" > "$folder/start-phase.txt.next"
  mv "$folder/start-phase.txt.next" "$folder/start-phase.txt"
  sync
  printf 'E900 capture: %s\n' "$1"
}
phase checking-mode
mode=$(tr -d '\r\n' < /sys/class/display/mode)
case "$mode" in
  1080p60hz) width=1920; height=1080; fps=60 ;;
  1080p50hz) width=1920; height=1080; fps=50 ;;
  720p60hz) width=1280; height=720; fps=60 ;;
  720p50hz) width=1280; height=720; fps=50 ;;
  *) echo "Unverified input mode: $mode" >&2; exit 1 ;;
esac
# Built-in drivers defer hardware probe until the late media buses are ready.
if [ ! -d /sys/bus/platform/drivers/viuin ]; then
  phase before-viuin-load
  modprobe tvin_viuin
fi
[ -d /sys/bus/platform/drivers/viuin ] || { echo 'VIUIN frontend is unavailable.' >&2; exit 1; }
parameter=/sys/module/tvin_vdin/parameters/gxlx2_capture
if [ ! -e "$parameter" ]; then
  phase before-vdin-load
  modprobe tvin_vdin
fi
[ -w "$parameter" ] || { echo 'The updated built-in VDIN diagnostic kernel is required.' >&2; exit 1; }
phase before-runtime-opt-in
printf '1\n' > "$parameter"
for instance in vdin0 vdin1; do
  if [ ! -w "/sys/class/vdin/$instance/attr" ]; then
    [ -d "/sys/bus/platform/devices/$instance" ] || { echo "Missing DT device: $instance" >&2; exit 1; }
    phase "before-$instance-probe"
    printf '%s\n' "$instance" > /sys/bus/platform/drivers_probe
    phase "after-$instance-probe"
  fi
done
attr=/sys/class/vdin/vdin1/attr
[ -w /sys/class/vdin/vdin0/attr ] && [ -w "$attr" ] || { echo 'Both VDIN instances must probe successfully; inspect dmesg.' >&2; exit 1; }
# TVIN_RGB444=0. Input timing stays at the current display mode; output is scaled.
phase before-conversion
printf 'conversion 640 360 0\n' > "$attr"
if [ "${E900_CAPTURE_PREPARE_ONLY:-0}" = 1 ]; then
  phase prepared-without-service
  printf 'VDIN instances prepared; capture service has not started.\n'
  exit 0
fi
phase before-service-start
printf 'v4l2start viuin %s %s %s 0 0 0 1\n' "$width" "$height" "$fps" > "$attr"
phase service-start-returned
printf 'boot_id=%s\ninput_mode=%s\nrequested_output=640x360 RGB444\n' "$(cat /proc/sys/kernel/random/boot_id)" "$mode" > /storage/e900-capture/session.txt
printf 'VDIN start returned success. Use e900-capture-ready.sh to verify a completed frame.\n'
