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
mkdir -p "$folder"
trap 'rm -f "$partial"' 0
trap 'exit 1' HUP INT TERM
printf 'capture_ready %s\n' "$partial" > "$attr"
mv "$partial" "$final"
sync
printf '%s\n' "$final"
