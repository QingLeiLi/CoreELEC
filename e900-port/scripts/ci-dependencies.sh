#!/usr/bin/env bash
set -euo pipefail
if [ "${GITHUB_ACTIONS:-}" != true ]; then
  echo 'This setup script is for an ephemeral GitHub Actions Linux runner.' >&2
  exit 1
fi
sudo apt-get update
deb_cache="$E900_WORK_ROOT/apt"
sudo install -d -m 0755 "$deb_cache" "$deb_cache/partial"
sudo env DEBIAN_FRONTEND=noninteractive apt-get -o "Dir::Cache::archives=$deb_cache" \
  -o APT::Keep-Downloaded-Packages=true install -y --no-install-recommends \
  ca-certificates locales sudo wget curl bash bc gcc-12 g++-12 clang sed patch \
  util-linux patchutils tar bzip2 gzip xz-utils zstd perl gawk gperf zip unzip \
  diffutils lzop make file xfonts-utils xsltproc default-jre-headless python3 \
  libc6-dev libncurses5-dev libjson-perl libxml-parser-perl libparse-yapp-perl \
  rdfind golang-1.22-go git openssh-client rsync
sudo locale-gen en_US.UTF-8
# Keep the runner's existing alternatives groups intact.
toolbin="$RUNNER_TEMP/e900-host-bin"
mkdir -p "$toolbin"
for tool in gcc g++ cpp gcov; do
  ln -sf "/usr/bin/$tool-12" "$toolbin/$tool"
done
printf '%s\n' "$toolbin" /usr/lib/go-1.22/bin >> "$GITHUB_PATH"
"$toolbin/gcc" --version
df -h
