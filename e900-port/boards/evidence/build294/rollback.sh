#!/bin/sh
set -eu
systemctl stop kodi
mount -o remount,rw /flash
trap 'mount -o remount,ro /flash' EXIT
for n in aml_autoscript s905_autoscript cfgload; do cp "/storage/e900-build294/previous/$n" "/flash/$n"; done
sync
mount -o remount,ro /flash
trap - EXIT
