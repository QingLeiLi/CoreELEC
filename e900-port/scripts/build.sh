#!/usr/bin/env bash
set -euo pipefail
action=${1:-status}
profile=${2:-identify}
PORT_ROOT=${E900_PORT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
WORK_ROOT=${E900_WORK_ROOT:-/work}
case "$profile" in baseline|identify|hdmi|decoder) ;; *) echo 'Unknown profile' >&2; exit 2 ;; esac
case "$action" in prepare|linux|media|image|shell|status) ;; *) exit 2 ;; esac
if [ "$(uname -s)" != Linux ] || [ "$(uname -m)" != x86_64 ]; then
  echo 'Use the linux/amd64 Docker container.' >&2; exit 1
fi
if [ "$(id -u)" = 0 ]; then
  echo 'CoreELEC builds must run as the non-root builder user.' >&2; exit 1
fi
mkdir -p "$WORK_ROOT"
exec 9>"$WORK_ROOT/.e900-build.lock"
if ! flock -n 9; then
  echo 'Another build is using this work volume.' >&2; exit 1
fi
export PROJECT=Amlogic-ce DEVICE=Amlogic-ng ARCH=arm
export SOURCES_DIR="$WORK_ROOT/downloads"
# Use one bounded cache for host and target compiler invocations.
export CCACHE_DIR="${CCACHE_DIR:-$WORK_ROOT/ccache}"
export LOCAL_CCACHE_DIR="${LOCAL_CCACHE_DIR:-$CCACHE_DIR}"
export CCACHE_MAXSIZE="${CCACHE_MAXSIZE:-1G}"
export CONCURRENCY_MAKE_LEVEL=${CONCURRENCY_MAKE_LEVEL:-4}
export THREADCOUNT=${THREADCOUNT:-1}
export TERM=${TERM:-xterm}
repo=$WORK_ROOT/CoreELEC-$profile
if [ "$action" = status ]; then
  df -h "$WORK_ROOT"
  printf 'Profile: %s\n' "$profile"
  if [ -d "$repo/.git" ]; then git -C "$repo" status --short; fi
  exit 0
fi
mkdir -p "$WORK_ROOT/downloads" "$WORK_ROOT/logs" "$WORK_ROOT/export/$profile"
exec > >(tee -a "$WORK_ROOT/logs/$profile-$(date -u +%Y%m%dT%H%M%SZ)-$action.log") 2>&1
if [ ! -d "$repo/.git" ]; then
  mkdir -p "$repo"
  git -C "$repo" init
  git -C "$repo" remote add origin https://github.com/CoreELEC/CoreELEC.git
fi
if ! git -C "$repo" rev-parse --verify HEAD >/dev/null 2>&1; then
  revision=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["coreelec"])' "$PORT_ROOT/pins.json")
  git -C "$repo" fetch --depth=1 origin "$revision"
  git -C "$repo" checkout --detach FETCH_HEAD
fi
python3 "$PORT_ROOT/scripts/install-patches.py" "$repo" "$profile"
cd "$repo"
python3 "$PORT_ROOT/scripts/build-cache.py" invalidate "$repo"
finish() {
  result=$?
  trap - EXIT
  E900_WORK_ROOT="$WORK_ROOT" python3 "$PORT_ROOT/scripts/export-artifacts.py" "$repo" "$profile" "$action" "$result" || true
  exit "$result"
}
trap finish EXIT
case "$action" in
  prepare) echo 'Pinned source and profile patches prepared; no compilation yet.' ;;
  shell) exec /bin/bash ;;
  linux) ./scripts/build linux ;;
  media) ./scripts/build media_modules-aml ;;
  image) make image ;;
esac
