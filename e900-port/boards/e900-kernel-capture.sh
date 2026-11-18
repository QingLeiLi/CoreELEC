#!/bin/sh
# Snapshot the ring before noisy display errors evict a driver Oops.
# Installed in /run by the diagnostic initrd; bounded to 90 seconds.
BB=/usr/bin/busybox
DIR=/storage/e900-kernel32
$BB mkdir -p "$DIR" || exit 1
n=0
while [ "$n" -lt 90 ]; do
  $BB dmesg >"$DIR/current.log"
  taint=$($BB cat /proc/sys/kernel/tainted)
  if [ "$((taint & 128))" -ne 0 ]; then
    $BB sleep 2
    $BB dmesg >"$DIR/oops.log"
    $BB cat /proc/modules >"$DIR/modules.txt"
    $BB ps >"$DIR/processes.txt"
    echo "Oops taint observed; snapshot frozen at sample $n" >"$DIR/result.txt"
    $BB sync
    exit 0
  fi
  n=$((n + 1))
  $BB sleep 1
done
echo "No Oops taint observed within 90 samples" >"$DIR/result.txt"
$BB sync
