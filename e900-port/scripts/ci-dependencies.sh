#!/usr/bin/env bash
set -euo pipefail
if [ "${GITHUB_ACTIONS:-}" != true ]; then
  echo 'This setup script is for an ephemeral GitHub Actions Linux runner.' >&2
  exit 1
fi
sudo apt-get update
sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  ca-certificates locales sudo wget curl bash bc gcc-12 g++-12 clang sed patch \
  util-linux patchutils tar bzip2 gzip xz-utils zstd perl gawk gperf zip unzip \
  diffutils lzop make file xfonts-utils xsltproc default-jre-headless python3 \
  libc6-dev libncurses5-dev libjson-perl libxml-parser-perl libparse-yapp-perl \
  rdfind golang-1.22-go git openssh-client rsync
sudo locale-gen en_US.UTF-8
sudo update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-12 100 \
  --slave /usr/bin/cpp cpp /usr/bin/cpp-12 \
  --slave /usr/bin/g++ g++ /usr/bin/g++-12 \
  --slave /usr/bin/gcov gcov /usr/bin/gcov-12
printf '/usr/lib/go-1.22/bin\n' >> "$GITHUB_PATH"
gcc --version
df -h
