#!/bin/sh
set -eu
mount -o remount,rw /flash
trap 'mount -o remount,ro /flash' EXIT
for n in aml_autoscript s905_autoscript cfgload; do cp "/storage/e900-boot-speed/previous/$n" "/flash/$n"; done
sync
mount -o remount,ro /flash
trap - EXIT
rm -f /storage/.config/system.d/kodi-waitonnetwork.service.d/20-e900-fast-boot.conf
systemctl daemon-reload
