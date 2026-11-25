#!/usr/bin/env python3
"""Install a version-checked patch profile into a dedicated CoreELEC checkout."""
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

PORT = pathlib.Path(__file__).resolve().parent.parent
PINS = json.loads((PORT / "pins.json").read_text())
LINUX_DIR = "projects/Amlogic-ce/devices/Amlogic-ng/patches/linux"
MEDIA_DIR = "projects/Amlogic-ce/packages/linux-drivers/amlogic/media_modules-aml/patches"
PROFILES = {
    "baseline": [],
    "identify": ["linux/0001-gxlx2-identity.patch",
                 "media/0001-gxlx2-identity-and-firmware-trace.patch"],
}
PROFILES["hdmi"] = PROFILES["identify"] + ["linux/0002-gxlx2-opt-in-hdmi-transport.patch"]
PROFILES["decoder"] = PROFILES["hdmi"] + ["media/0002-gxlx2-experimental-clock-registration.patch",
                                         "linux/0003-e900v21c-usb-board.patch",
                                         "linux/0005-gxlx2-optional-di-clock.patch",
                                         "linux/0006-gxlx2-direct-media-register-buses.patch",
                                         "media/0003-gxlx2-vld-dmc-channel.patch",
                                         "linux/0007-gxlx2-post2-matrix-guard.patch",
                                         "linux/0008-gxlx2-legacy-video-pipeline.patch",
                                         "linux/0009-gxlx2-mif-selection-probe.patch",
                                         "linux/0010-gxlx2-late-video-init-probe.patch",
                                         "linux/0011-gxlx2-synchronous-frame-capture.patch",
                                         "linux/0017-gxlx2-display-stage-hooks.patch",
                                         "linux/0019-gxlx2-deferred-video-register-init.patch",
                                         "linux/0020-gxlx2-netpoll-no-sleep.patch",
                                         "linux/0021-gxlx2-sr0-capability-guard.patch",
                                         "linux/0022-gxlx2-debug-foundation.patch",
                                         "linux/0023-gxlx2-gen3-source-experiment.patch",
                                         "linux/0024-gxlx2-rmw-and-osd-diagnostics.patch",
                                         "linux/0025-gxlx2-display-transition-evidence.patch",
                                         "linux/0027-gxlx2-intermediate-pixel-probes.patch",
                                         "linux/0028-gxlx2-blend-boundary-experiment.patch",
                                         "linux/0029-gxlx2-blend-transition-recorder.patch",
                                         "linux/0030-gxlx2-runtime-sr-capability-guard.patch",
                                         "linux/0031-gxlx2-pps-csc-transition-evidence.patch",
                                         "linux/0032-gxlx2-independent-video-rdma-watchdog.patch",
                                         "linux/0033-gxlx2-hdr-submission-evidence.patch",
                                         "linux/0035-gxlx2-pps-hdr-submission-tables.patch"]
BOARD = "gxlx2_p291_1g_e900v21c"
HOST_CODEGEN = dict(schema=1, cflags="-march=x86-64 -mtune=generic",
                    upstream_optimize_sha256="8291f139ca78f0d949cc85e6f94b6d48c946fd28485c8ba12d5c810aaec61429")


CAPTURE_PATCHES = [
    "linux/0012-gxlx2-vdin-routing.patch",
    "linux/0013-gxlx2-vdin-dma-lifecycle.patch",
    "linux/0014-gxlx2-vdin-ready-snapshot.patch",
    "linux/0015-e900-vdin-clock-bindings.patch",
    "linux/0016-gxlx2-vdin-builtin-linkage.patch",
    "linux/0018-gxlx2-vdin-observe-before-ack.patch",
    "linux/0026-gxlx2-vdin-fresh-request-evidence.patch",
]
CAPTURE_CONFIG = "projects/Amlogic-ce/devices/Amlogic-ng/linux/linux.aarch64.conf"
CAPTURE_CONFIG_BASE_SHA256 = "9bf441cc9ed301de8b3be8ab05cdf2e3d0de9fc4fd50f8e02ec848f378088362"
CAPTURE_CONFIG_EXTRA = "\n# E900 optional completed-frame VDIN diagnostics\nCONFIG_AMLOGIC_MEDIA_TVIN=y\nCONFIG_AMLOGIC_MEDIA_VDIN=y\nCONFIG_AMLOGIC_MEDIA_VIUIN=y\n"
CAPTURE_BUILTIN_DEPS = ("MEDIA_SUPPORT", "VIDEO_DEV", "VIDEO_V4L2",
                        "VIDEOBUF2_CORE", "VIDEOBUF2_MEMOPS", "VIDEOBUF2_DMA_CONTIG")
CAPTURE_CONFIG_LEGACY_EXTRA = CAPTURE_CONFIG_EXTRA.replace("CONFIG_AMLOGIC_MEDIA_VDIN=y", "CONFIG_AMLOGIC_MEDIA_VDIN=m").replace("CONFIG_AMLOGIC_MEDIA_VIUIN=y", "CONFIG_AMLOGIC_MEDIA_VIUIN=m")


def selected_patches(profile):
    selected = list(PROFILES[profile])
    if os.environ.get("E900_SOURCE_TRACE", "0") == "1":
        if profile != "decoder":
            raise RuntimeError("Source tracing requires the decoder board profile")
        selected.append("linux/0004-e900-source-boot-trace.patch")
    capture = os.environ.get("E900_VDIN_CAPTURE", "0")
    if capture not in {"0", "1"}:
        raise ValueError("E900_VDIN_CAPTURE must be 0 or 1")
    if capture == "1":
        if profile != "decoder":
            raise RuntimeError("VDIN diagnostics require the decoder board profile")
        selected.extend(CAPTURE_PATCHES)
    return selected


def capture_config_fix(repo, enabled):
    content = (repo / CAPTURE_CONFIG).read_text()
    base = content
    for managed_block in (CAPTURE_CONFIG_EXTRA, CAPTURE_CONFIG_LEGACY_EXTRA):
        if content.endswith(managed_block):
            base = content[:-len(managed_block)].replace(
                "CONFIG_AMLOGIC_MEDIA_VIN=y", "# CONFIG_AMLOGIC_MEDIA_VIN is not set", 1)
            if (hashlib.sha256(base.encode()).hexdigest() != CAPTURE_CONFIG_BASE_SHA256 and
                    managed_block == CAPTURE_CONFIG_EXTRA and
                    all(f"CONFIG_{name}=y" in base.splitlines() for name in CAPTURE_BUILTIN_DEPS)):
                for name in CAPTURE_BUILTIN_DEPS:
                    base = base.replace(f"CONFIG_{name}=y", f"CONFIG_{name}=m", 1)
            break
    if hashlib.sha256(base.encode()).hexdigest() != CAPTURE_CONFIG_BASE_SHA256:
        raise RuntimeError("Unmanaged or locally edited capture kernel configuration")
    updated = base
    metadata = None
    if enabled:
        updated = base.replace("# CONFIG_AMLOGIC_MEDIA_VIN is not set", "CONFIG_AMLOGIC_MEDIA_VIN=y", 1)
        for name in CAPTURE_BUILTIN_DEPS:
            if updated.splitlines().count(f"CONFIG_{name}=m") != 1:
                raise RuntimeError("Unexpected capture builtin dependency: " + name)
            updated = updated.replace(f"CONFIG_{name}=m", f"CONFIG_{name}=y", 1)
        updated += CAPTURE_CONFIG_EXTRA
        metadata = dict(destination=CAPTURE_CONFIG, base_sha256=CAPTURE_CONFIG_BASE_SHA256,
                        sha256=hashlib.sha256(updated.encode()).hexdigest())
    return CAPTURE_CONFIG, updated, metadata


def invalidated_packages(previous, state):
    if previous["pins"] != state["pins"] or previous["profile"] != state["profile"]:
        raise RuntimeError("Incompatible cached pins or profile")
    if previous.get("host_codegen") != state.get("host_codegen"):
        raise RuntimeError("Incompatible host code generation policy; use a fresh binary build cache")
    old = {entry["source"]: entry["sha256"] for entry in previous["patches"]}
    new = {entry["source"]: entry["sha256"] for entry in state["patches"]}
    changed = {name for name in old.keys() | new.keys() if old.get(name) != new.get(name)}
    packages = set()
    if any(name.startswith("linux/") for name in changed):
        packages.update(["linux", "media_modules-aml"])
    if any(name.startswith("media/") for name in changed):
        packages.add("media_modules-aml")
    old_sources = {entry["package"]: entry for entry in previous.get("source_downloads", [])}
    new_sources = {entry["package"]: entry for entry in state.get("source_downloads", [])}
    changed_sources = {name for name in old_sources.keys() | new_sources.keys()
                       if old_sources.get(name) != new_sources.get(name)}
    if changed_sources - {"keyutils", "usbutils", "connman", "wireguard-linux-compat", "wireguard-tools", "u-boot-tools", "megatools"}:
        raise RuntimeError("Unexpected source download override")
    packages.update(changed_sources)
    old_install = {entry["package"]: entry for entry in previous.get("package_install_fixes", [])}
    new_install = {entry["package"]: entry for entry in state.get("package_install_fixes", [])}
    changed_install = {name for name in old_install.keys() | new_install.keys()
                       if old_install.get(name) != new_install.get(name)}
    if changed_install - {"media_modules-aml"}:
        raise RuntimeError("Unexpected package installation policy change")
    packages.update(changed_install)
    if (previous.get("build_options") != state.get("build_options") or
            previous.get("capture_config") != state.get("capture_config")):
        packages.update(["linux", "media_modules-aml"])
    return sorted(packages)


def validate_packages(repo):
    for relative, key in [
        ("projects/Amlogic-ce/packages/linux/package.mk", "linux"),
        ("projects/Amlogic-ce/packages/linux-drivers/amlogic/media_modules-aml/package.mk", "media_modules"),
    ]:
        content = (repo / relative).read_text()
        if not re.search(r'PKG_VERSION="' + PINS[key] + '"', content):
            raise RuntimeError(f"Unexpected package revision: {relative}")


def keyutils_download_fix(repo):
    relative = "packages/sysutils/keyutils/package.mk"
    original = (repo / relative).read_text()
    digest = "a61d5706136ae4c05bd48f86186bcfdbd88dd8bd5107e3e195c924cfc1b39bb4"
    upstream = "https://git.kernel.org/pub/scm/linux/kernel/git/dhowells/keyutils.git/snapshot/${PKG_NAME}-${PKG_VERSION}.tar.gz"
    mirror = "https://deb.debian.org/debian/pool/main/k/keyutils/keyutils_${PKG_VERSION}.orig.tar.gz"
    source_name = 'PKG_SOURCE_NAME="${PKG_NAME}-${PKG_VERSION}.tar.gz"'
    if ('PKG_VERSION="1.6.3"' not in original or f'PKG_SHA256="{digest}"' not in original):
        raise RuntimeError("Unexpected keyutils version or checksum; refusing source URL override")
    urls = re.findall(r'^PKG_URL="([^"]*)"$', original, re.M)
    if len(urls) != 1 or urls[0] not in {upstream, mirror}:
        raise RuntimeError("Unexpected keyutils URL; refusing to overwrite local changes")
    names = re.findall(r'^PKG_SOURCE_NAME=.*$', original, re.M)
    if names and names != [source_name]:
        raise RuntimeError("Unexpected keyutils source filename")
    replacement = f'PKG_URL="{mirror}"'
    if not names:
        replacement += "\n" + source_name
    content = re.sub(r'^PKG_URL="[^"]*"$', lambda _: replacement, original, flags=re.M)
    metadata = dict(package="keyutils", version="1.6.3", archive_sha256=digest,
                    url=mirror, destination=relative,
                    package_file_sha256=hashlib.sha256(content.encode()).hexdigest())
    return relative, content, metadata


def usbutils_download_fix(repo):
    relative = "packages/sysutils/usbutils/package.mk"
    original = (repo / relative).read_text()
    digest = "a6a25ffdcf9103e38d7a44732aca17073f4e602b92e4ae55625231a82702e05b"
    upstream = "http://kernel.org/pub/linux/utils/usb/usbutils/${PKG_NAME}-${PKG_VERSION}.tar.xz"
    mirror = "https://mirrors.edge.kernel.org/pub/linux/utils/usb/usbutils/${PKG_NAME}-${PKG_VERSION}.tar.xz"
    if ('PKG_VERSION="017"' not in original or f'PKG_SHA256="{digest}"' not in original):
        raise RuntimeError("Unexpected usbutils version or checksum; refusing source URL override")
    urls = re.findall(r'^PKG_URL="([^"]*)"$', original, re.M)
    if len(urls) != 1 or urls[0] not in {upstream, mirror}:
        raise RuntimeError("Unexpected usbutils URL; refusing to overwrite local changes")
    source_name = 'PKG_SOURCE_NAME="${PKG_NAME}-${PKG_VERSION}.tar.xz"'
    names = re.findall(r'^PKG_SOURCE_NAME=.*$', original, re.M)
    if names and names != [source_name]:
        raise RuntimeError("Unexpected usbutils source filename")
    replacement = f'PKG_URL="{mirror}"'
    if not names:
        replacement += "\n" + source_name
    content = re.sub(r'^PKG_URL="[^"]*"$', lambda _: replacement, original, flags=re.M)
    metadata = dict(package="usbutils", version="017", archive_sha256=digest,
                    url=mirror, destination=relative,
                    package_file_sha256=hashlib.sha256(content.encode()).hexdigest())
    return relative, content, metadata


def connman_download_fix(repo):
    relative = "packages/network/connman/package.mk"
    original = (repo / relative).read_text()
    snapshot_digest = "22acfe9d5958d7983090232334a692eee66a12f3077e09e4f360276608156738"
    release_digest = "b8f5ab5d109d033edebe5b0564d20c9b7b9546a607195cdadc6754eb328b6f6e"
    upstream = "https://git.kernel.org/pub/scm/network/connman/connman.git/snapshot/connman-${PKG_VERSION}.tar.gz"
    mirror = "https://mirrors.edge.kernel.org/pub/linux/network/connman/connman-${PKG_VERSION}.tar.gz"
    source_name = 'PKG_SOURCE_NAME="connman-${PKG_VERSION}-release.tar.gz"'
    versions = re.findall(r'^PKG_VERSION="([^"]*)"$', original, re.M)
    urls = re.findall(r'^PKG_URL="([^"]*)"$', original, re.M)
    digests = re.findall(r'^PKG_SHA256="([^"]*)"$', original, re.M)
    names = re.findall(r'^PKG_SOURCE_NAME=.*$', original, re.M)
    # The release archive has identical common source files plus autotools output.
    # It is a different archive, with its own checksum and distinct cache filename.
    if versions != ["1.43"] or not (
            (urls == [upstream] and digests == [snapshot_digest] and not names)
            or (urls == [mirror] and digests == [release_digest] and names == [source_name])):
        raise RuntimeError("Unexpected connman source configuration; refusing release archive override")
    replacement = f'PKG_URL="{mirror}"'
    if not names:
        replacement += "\n" + source_name
    content = re.sub(r'^PKG_URL="[^"]*"$', lambda _: replacement, original, flags=re.M)
    content = re.sub(r'^PKG_SHA256="[^"]*"$', f'PKG_SHA256="{release_digest}"', content, flags=re.M)
    metadata = dict(package="connman", version="1.43", archive_sha256=release_digest,
                    original_snapshot_sha256=snapshot_digest, archive_kind="official-release",
                    url=mirror, destination=relative,
                    package_file_sha256=hashlib.sha256(content.encode()).hexdigest())
    return relative, content, metadata


def wireguard_download_fix(repo):
    relative = "packages/network/wireguard-linux-compat/package.mk"
    original = (repo / relative).read_text()
    digest = "362d412693c8fe82de00283435818d5c5def7f15e2433a07a9fe99d0518f63c0"
    upstream = "https://git.zx2c4.com/wireguard-linux-compat/snapshot/wireguard-linux-compat-$PKG_VERSION.tar.xz"
    mirror = "https://sources.buildroot.net/wireguard-linux-compat/wireguard-linux-compat-${PKG_VERSION}.tar.xz"
    source_name = 'PKG_SOURCE_NAME="${PKG_NAME}-${PKG_VERSION}.tar.xz"'
    if (re.findall(r'^PKG_VERSION="([^"]*)"$', original, re.M) != ["1.0.20220627"]
            or re.findall(r'^PKG_SHA256="([^"]*)"$', original, re.M) != [digest]
            or re.findall(r'^PKG_URL="([^"]*)"$', original, re.M) not in [[upstream], [mirror]]):
        raise RuntimeError("Unexpected WireGuard source configuration; refusing download override")
    names = re.findall(r'^PKG_SOURCE_NAME=.*$', original, re.M)
    if names and names != [source_name]:
        raise RuntimeError("Unexpected WireGuard source filename")
    replacement = f'PKG_URL="{mirror}"'
    if not names:
        replacement += "\n" + source_name
    content = re.sub(r'^PKG_URL="[^"]*"$', lambda _: replacement, original, flags=re.M)
    metadata = dict(package="wireguard-linux-compat", version="1.0.20220627", archive_sha256=digest,
                    url=mirror, destination=relative,
                    package_file_sha256=hashlib.sha256(content.encode()).hexdigest())
    return relative, content, metadata


def wireguard_tools_download_fix(repo):
    relative = "packages/network/wireguard-tools/package.mk"
    original = (repo / relative).read_text()
    old_digest = "69de713458a887cddb46b2fd1d43bf20548f693136af95792e65ec925538c770"
    digest = "97ff31489217bb265b7ae850d3d0f335ab07d2652ba1feec88b734bc96bd05ac"
    upstream = "https://git.zx2c4.com/wireguard-tools/snapshot/wireguard-tools-v${PKG_VERSION}.tar.xz"
    mirror = "https://sources.buildroot.net/wireguard-tools/wireguard-tools-${PKG_VERSION}.tar.xz"
    source_name = 'PKG_SOURCE_NAME="wireguard-tools-${PKG_VERSION}-buildroot.tar.xz"'
    versions = re.findall(r'^PKG_VERSION="([^"]*)"$', original, re.M)
    urls = re.findall(r'^PKG_URL="([^"]*)"$', original, re.M)
    digests = re.findall(r'^PKG_SHA256="([^"]*)"$', original, re.M)
    names = re.findall(r'^PKG_SOURCE_NAME=.*$', original, re.M)
    if versions != ["1.0.20210914"] or not (
            (urls == [upstream] and digests == [old_digest] and not names)
            or (urls == [mirror] and digests == [digest] and names == [source_name])):
        raise RuntimeError("Unexpected WireGuard tools source configuration")
    replacement = f'PKG_URL="{mirror}"'
    if not names:
        replacement += "\n" + source_name
    content = re.sub(r'^PKG_URL="[^"]*"$', lambda _: replacement, original, flags=re.M)
    content = re.sub(r'^PKG_SHA256="[^"]*"$', f'PKG_SHA256="{digest}"', content, flags=re.M)
    metadata = dict(package="wireguard-tools", version="1.0.20210914", archive_sha256=digest,
                    original_archive_sha256=old_digest, url=mirror, destination=relative,
                    package_file_sha256=hashlib.sha256(content.encode()).hexdigest())
    return relative, content, metadata


def u_boot_tools_download_fix(repo):
    relative = "projects/Amlogic-ce/packages/tools/u-boot-tools/package.mk"
    original = (repo / relative).read_text()
    digest = "e49337262ecac44dbdeac140f2c6ebd1eba345e0162b0464172e7f05583ed7bb"
    upstream = "ftp://ftp.denx.de/pub/u-boot/u-boot-$PKG_VERSION.tar.bz2"
    mirror = "https://sources.buildroot.net/u-boot-${PKG_VERSION}.tar.bz2"
    source_name = 'PKG_SOURCE_NAME="${PKG_NAME}-${PKG_VERSION}.tar.bz2"'
    if (re.findall(r'^PKG_VERSION="([^"]*)"$', original, re.M) != ["2016.03"]
            or re.findall(r'^PKG_SHA256="([^"]*)"$', original, re.M) != [digest]
            or re.findall(r'^PKG_URL="([^"]*)"$', original, re.M) not in [[upstream], [mirror]]):
        raise RuntimeError("Unexpected u-boot-tools source configuration; refusing download override")
    names = re.findall(r'^PKG_SOURCE_NAME=.*$', original, re.M)
    if names and names != [source_name]:
        raise RuntimeError("Unexpected u-boot-tools source filename")
    replacement = f'PKG_URL="{mirror}"'
    if not names:
        replacement += "\n" + source_name
    content = re.sub(r'^PKG_URL="[^"]*"$', lambda _: replacement, original, flags=re.M)
    metadata = dict(package="u-boot-tools", version="2016.03", archive_sha256=digest,
                    url=mirror, destination=relative,
                    package_file_sha256=hashlib.sha256(content.encode()).hexdigest())
    return relative, content, metadata


def megatools_download_fix(repo):
    relative = "packages/tools/megatools/package.mk"
    original = (repo / relative).read_text()
    digest = "8dc1ca348633fd49de7eb832b323e8dc295f1c55aefb484d30e6475218558bdb"
    upstream = "https://megatools.megous.com/builds/megatools-${PKG_VERSION}.tar.gz"
    mirror = "https://deb.debian.org/debian/pool/main/m/megatools/megatools_${PKG_VERSION}.orig.tar.gz"
    source_name = 'PKG_SOURCE_NAME="${PKG_NAME}-${PKG_VERSION}.tar.gz"'
    if (re.findall(r'^PKG_VERSION="([^"]*)"$', original, re.M) != ["1.10.3"]
            or re.findall(r'^PKG_SHA256="([^"]*)"$', original, re.M) != [digest]
            or re.findall(r'^PKG_URL="([^"]*)"$', original, re.M) not in [[upstream], [mirror]]):
        raise RuntimeError("Unexpected megatools source configuration; refusing download override")
    names = re.findall(r'^PKG_SOURCE_NAME=.*$', original, re.M)
    if names and names != [source_name]:
        raise RuntimeError("Unexpected megatools source filename")
    replacement = f'PKG_URL="{mirror}"'
    if not names:
        replacement += "\n" + source_name
    content = re.sub(r'^PKG_URL="[^"]*"$', lambda _: replacement, original, flags=re.M)
    metadata = dict(package="megatools", version="1.10.3", archive_sha256=digest,
                    url=mirror, destination=relative,
                    package_file_sha256=hashlib.sha256(content.encode()).hexdigest())
    return relative, content, metadata


def host_codegen_fix(repo):
    relative = "config/optimize"
    original = (repo / relative).read_text()
    native = 'HOST_CFLAGS="-march=native -O2 -Wall -pipe -I$TOOLCHAIN/include"'
    portable = 'HOST_CFLAGS="' + HOST_CODEGEN["cflags"] + ' -O2 -Wall -pipe -I$TOOLCHAIN/include"'
    normalized = original.replace(portable, native)
    if (hashlib.sha256(normalized.encode()).hexdigest() != HOST_CODEGEN["upstream_optimize_sha256"]
            or normalized.count(native) != 1):
        raise RuntimeError("Unexpected host optimization config; refusing to overwrite local edits")
    content = normalized.replace(native, portable)
    metadata = dict(HOST_CODEGEN, destination=relative,
                    file_sha256=hashlib.sha256(content.encode()).hexdigest())
    return relative, content, metadata


def media_module_install_fix(repo):
    relative = "projects/Amlogic-ce/packages/linux-drivers/amlogic/media_modules-aml/package.mk"
    original = (repo / relative).read_text()
    old = r"""    find $PKG_BUILD/ -name \*.ko -not -path '*/\.*' -exec cp {} $INSTALL/$(get_full_module_dir)/$PKG_NAME \;"""
    new = r"""  (
    cd "$PKG_BUILD" || exit 1
    find . -path '*/.*' -prune -o -type f -name \*.ko -exec cp {} "$INSTALL/$(get_full_module_dir)/$PKG_NAME" \;
  )
  if [ -z "$(find "$INSTALL/$(get_full_module_dir)/$PKG_NAME" -maxdepth 1 -type f -name \*.ko -print -quit)" ]; then
    echo "No media modules were installed" >&2
    return 1
  fi"""
    normalized = original.replace(new, old)
    if (hashlib.sha256(normalized.encode()).hexdigest() != "c6b45a180ceea205066c255f2fabe8329c35eae05baebb2b65054e3583597438"
            or normalized.count(old) != 1):
        raise RuntimeError("Unexpected media module package recipe; refusing local edits")
    content = normalized.replace(old, new)
    metadata = dict(package="media_modules-aml", policy="relative-module-discovery-v1", destination=relative,
                    file_sha256=hashlib.sha256(content.encode()).hexdigest())
    return relative, content, metadata


def install(repo, profile):
    if profile not in PROFILES:
        raise ValueError("Unknown profile")
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    if head != PINS["coreelec"]:
        raise RuntimeError(f"Refusing unpinned checkout: {head}")
    selected = selected_patches(profile)
    marker = repo / ".e900-profile.json"
    previous = json.loads(marker.read_text()) if marker.exists() else None
    capture_enabled = os.environ.get("E900_VDIN_CAPTURE", "0") == "1"
    capture_fix = capture_config_fix(repo, capture_enabled) if capture_enabled or (previous or {}).get("capture_config") else None
    validate_packages(repo)
    host_path, host_content, host_metadata = host_codegen_fix(repo)
    media_path, media_content, media_metadata = media_module_install_fix(repo)
    source_fixes = [keyutils_download_fix(repo), usbutils_download_fix(repo), connman_download_fix(repo),
                    wireguard_download_fix(repo), wireguard_tools_download_fix(repo),
                    u_boot_tools_download_fix(repo), megatools_download_fix(repo)]
    options = PORT / "boards/usb-build.options"
    option_content = options.read_text() if profile == "decoder" else None
    option_destination = repo / ".coreelec/options"
    option_metadata = dict(destination=".coreelec/options", sha256=hashlib.sha256(option_content.encode()).hexdigest()) if option_content else None
    entries = []
    for relative in selected:
        source = PORT / "patches" / relative
        dest_dir = LINUX_DIR if relative.startswith("linux/") else MEDIA_DIR
        destination = repo / dest_dir / ("9000-e900-" + source.name)
        entries.append(dict(source=relative, destination=str(destination.relative_to(repo)),
                            sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
    state = dict(profile=profile, pins=PINS, patches=entries,
                 capture_config=capture_fix[2] if capture_fix else None,
                 source_downloads=[entry[2] for entry in source_fixes],
                 package_install_fixes=[media_metadata],
                 host_codegen=host_metadata,
                 build_options=option_metadata, board_dtb=BOARD if profile == "decoder" else None,
                 status="experimental-unvalidated")

    old_host = (previous or {}).get("host_codegen")
    if old_host and hashlib.sha256((repo / host_path).read_bytes()).hexdigest() != old_host["file_sha256"]:
        raise RuntimeError("Locally edited host optimization config; refusing binary cache reuse")
    if any(repo.glob("build.*")) and (previous or {}).get("host_codegen") != host_metadata:
        raise RuntimeError("Incompatible native/unknown host binary cache; use a fresh build tree. "
                           "Source downloads can still be reused.")
    old_options = (previous or {}).get("build_options")
    if option_destination.exists():
        if not old_options or hashlib.sha256(option_destination.read_bytes()).hexdigest() != old_options["sha256"]:
            raise RuntimeError("Unmanaged or locally edited .coreelec/options")
    invalidate = []
    if previous and previous != state and any(repo.glob("build.*")):
        if os.environ.get("E900_INCREMENTAL_REUSE") != "1":
            raise RuntimeError("Patch profile changed after building. Use a fresh build volume "
                               "or explicitly enable checked incremental reuse.")
        invalidate = invalidated_packages(previous, state)
    # Do not overwrite a user's edits, even in files this script installed before.
    for entry in (previous or {}).get("patches", []):
        dest = repo / entry["destination"]
        if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest() != entry["sha256"]:
            raise RuntimeError(f"Local patch edits found: {dest}")
    for entry in entries:
        dest = repo / entry["destination"]
        if dest.exists() and not previous:
            raise RuntimeError(f"Unmanaged patch already exists: {dest}")
    for entry in (previous or {}).get("patches", []):
        if entry["destination"] not in {e["destination"] for e in entries}:
            (repo / entry["destination"]).unlink(missing_ok=True)
    for entry in entries:
        dest = repo / entry["destination"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((PORT / "patches" / entry["source"]).read_bytes())
    for source_path, source_content, _ in source_fixes:
        (repo / source_path).write_text(source_content)
    (repo / host_path).write_text(host_content)
    (repo / media_path).write_text(media_content)
    if capture_fix:
        (repo / capture_fix[0]).write_text(capture_fix[1])
    if option_content:
        option_destination.parent.mkdir(exist_ok=True)
        option_destination.write_text(option_content)
    elif old_options:
        option_destination.unlink(missing_ok=True)
    if invalidate:
        pending = repo / ".e900-invalidate.json"
        existing = json.loads(pending.read_text()) if pending.exists() else []
        pending.write_text(json.dumps(sorted(set(existing) | set(invalidate))) + "\n")
        print("Incremental update: rebuild " + ", ".join(invalidate) + "; toolchain preserved")
    marker.write_text(json.dumps(state, indent=2) + "\n")
    print(f"Profile {profile}: {len(entries)} candidate patches installed; board DTB: {state['board_dtb'] or 'none'}.")


if __name__ == "__main__":
    try:
        install(pathlib.Path(sys.argv[1]).resolve(), sys.argv[2])
    except (RuntimeError, ValueError, IndexError) as exc:
        sys.exit(str(exc))
