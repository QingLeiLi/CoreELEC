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
                                         "linux/0003-e900v21c-usb-board.patch"]
BOARD = "gxlx2_p291_1g_e900v21c"
HOST_CODEGEN = dict(schema=1, cflags="-march=x86-64 -mtune=generic",
                    upstream_optimize_sha256="8291f139ca78f0d949cc85e6f94b6d48c946fd28485c8ba12d5c810aaec61429")


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
    if previous.get("build_options") != state.get("build_options"):
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


def install(repo, profile):
    if profile not in PROFILES:
        raise ValueError("Unknown profile")
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    if head != PINS["coreelec"]:
        raise RuntimeError(f"Refusing unpinned checkout: {head}")
    validate_packages(repo)
    host_path, host_content, host_metadata = host_codegen_fix(repo)
    source_fixes = [keyutils_download_fix(repo), usbutils_download_fix(repo), connman_download_fix(repo),
                    wireguard_download_fix(repo), wireguard_tools_download_fix(repo),
                    u_boot_tools_download_fix(repo), megatools_download_fix(repo)]
    options = PORT / "boards/usb-build.options"
    option_content = options.read_text() if profile == "decoder" else None
    option_destination = repo / ".coreelec/options"
    option_metadata = dict(destination=".coreelec/options", sha256=hashlib.sha256(option_content.encode()).hexdigest()) if option_content else None
    entries = []
    selected = list(PROFILES[profile])
    if os.environ.get("E900_SOURCE_TRACE", "0") == "1":
        if profile != "decoder":
            raise RuntimeError("Source tracing requires the decoder board profile")
        selected.append("linux/0004-e900-source-boot-trace.patch")
    for relative in selected:
        source = PORT / "patches" / relative
        dest_dir = LINUX_DIR if relative.startswith("linux/") else MEDIA_DIR
        destination = repo / dest_dir / ("9000-e900-" + source.name)
        entries.append(dict(source=relative, destination=str(destination.relative_to(repo)),
                            sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
    state = dict(profile=profile, pins=PINS, patches=entries,
                 source_downloads=[entry[2] for entry in source_fixes],
                 host_codegen=host_metadata,
                 build_options=option_metadata, board_dtb=BOARD if profile == "decoder" else None,
                 status="experimental-unvalidated")
    marker = repo / ".e900-profile.json"
    previous = json.loads(marker.read_text()) if marker.exists() else None
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
