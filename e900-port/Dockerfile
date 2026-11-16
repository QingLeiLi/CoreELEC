# Derived from CoreELEC 21.3-Omega tools/docker/jammy/Dockerfile.
FROM ubuntu:22.04
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates locales sudo wget curl bash bc gcc-12 g++-12 sed patch util-linux \
    patchutils tar bzip2 gzip xz-utils zstd perl gawk gperf zip unzip diffutils \
    lzop make file xfonts-utils xsltproc default-jre-headless python3 \
    libc6-dev libncurses5-dev libjson-perl libxml-parser-perl libparse-yapp-perl \
    rdfind golang-1.22-go git openssh-client rsync \
 && locale-gen en_US.UTF-8 \
 && mkdir -p /opt/e900-host-bin \
 && ln -s /usr/bin/gcc-12 /opt/e900-host-bin/gcc \
 && ln -s /usr/bin/g++-12 /opt/e900-host-bin/g++ \
 && ln -s /usr/bin/cpp-12 /opt/e900-host-bin/cpp \
 && ln -s /usr/bin/gcov-12 /opt/e900-host-bin/gcov \
 && ln -s /usr/lib/go-1.22 /usr/lib/go \
 && ln -s /usr/lib/go-1.22/bin/go /usr/bin/go \
 && ln -s /usr/lib/go-1.22/bin/gofmt /usr/bin/gofmt \
 && useradd --create-home --uid 1000 --shell /bin/bash builder \
 && printf 'builder ALL=(ALL) NOPASSWD:ALL\n' > /etc/sudoers.d/builder \
 && chmod 0440 /etc/sudoers.d/builder \
 && mkdir -p /work && chown builder:builder /work \
 && rm -rf /var/lib/apt/lists/*
ENV LANG=en_US.UTF-8 LANGUAGE=en_US:en LC_ALL=en_US.UTF-8
ENV PATH="/opt/e900-host-bin:${PATH}"
USER builder
WORKDIR /work
ENTRYPOINT ["/bin/bash", "/port/scripts/build.sh"]
