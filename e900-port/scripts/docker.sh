#!/usr/bin/env bash
set -euo pipefail
PORT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
IMAGE=${E900_BUILDER_IMAGE:-e900-coreelec-builder:21.3}
VOLUME=${E900_BUILD_VOLUME:-e900-coreelec-work}
action=${1:-help}
if ! command -v docker >/dev/null; then
  echo 'Docker CLI is not installed. Install and start Docker Desktop first.' >&2
  exit 1
fi
case "$action" in
  build-env)
    exec docker build --platform linux/amd64 -t "$IMAGE" "$PORT_DIR"
    ;;
  prepare|linux|media|image|shell|status)
    shift
    tty_args=()
    if [ -t 0 ] && [ -t 1 ]; then tty_args=(-it); fi
    exec docker run --rm "${tty_args[@]}" --platform linux/amd64 \
      --mount "type=volume,source=$VOLUME,target=/work" \
      --mount "type=bind,source=$PORT_DIR,target=/port,readonly" \
      -e "CONCURRENCY_MAKE_LEVEL=${E900_JOBS:-4}" \
      -e "THREADCOUNT=${E900_THREADS:-1}" \
      "$IMAGE" "$action" "$@"
    ;;
  export)
    profile=${2:-identify}
    case "$profile" in baseline|identify|hdmi|decoder) ;; *) exit 2 ;; esac
    mkdir -p "$PORT_DIR/output/$profile"
    # This container exits before copying; its filesystem stays until docker rm.
    container=$(docker create --platform linux/amd64 \
      --mount "type=volume,source=$VOLUME,target=/work" \
      --entrypoint /bin/true "$IMAGE")
    trap 'docker rm "$container" >/dev/null' EXIT
    docker cp "$container:/work/export/$profile/." "$PORT_DIR/output/$profile/"
    ;;
  *)
    echo 'Usage: bash scripts/docker.sh build-env'
    echo '       bash scripts/docker.sh {prepare|linux|media|image|shell|status} [baseline|identify|hdmi|decoder]'
    echo '       bash scripts/docker.sh export [profile]'
    ;;
esac
