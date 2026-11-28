#!/bin/sh
set -eu
p=/storage/e900-build294
[ "$(cat /sys/class/vdec/vdec_status)" = 'No vdec.' ]
grep -q 'SYSTEM_IMAGE=SYSTEM293 BOOT_IMAGE=e900-Image293H' /proc/cmdline
cd "$p"
tar -xf payload.tar
need_kb=$(du -k SYSTEM294 e900-Image294 e900-uInitrd294 e900-dtb294 | awk '{n+=$1} END {print n+16384}')
free_kb=$(df -k /flash | awk 'NR==2 {print $4}')
[ "$free_kb" -gt "$need_kb" ] || { echo 'Insufficient flash reserve'; exit 1; }
for n in SYSTEM294 e900-Image294 e900-uInitrd294 e900-dtb294 boot294.script; do [ -s "$n" ]; done
systemctl stop kodi
mount -o remount,rw,async /flash
trap 'mount -o remount,ro,sync /flash' EXIT
for n in SYSTEM294 e900-Image294 e900-uInitrd294 e900-dtb294; do
 cp "$n" "/flash/$n.new"
 [ "$(stat -c %s "$n")" = "$(stat -c %s "/flash/$n.new")" ]
 mv "/flash/$n.new" "/flash/$n"
done
sync
# Switch boot entrypoints only after all matching new payloads exist.
for n in aml_autoscript s905_autoscript cfgload; do
 cp boot294.script "/flash/$n.new"
 mv "/flash/$n.new" "/flash/$n"
done
sync
mount -o remount,ro,sync /flash
trap - EXIT
echo DEPLOYED_BUILD294
df -h /flash
