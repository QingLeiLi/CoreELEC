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


def invalidated_packages(previous, state):
    if previous["pins"] != state["pins"] or previous["profile"] != state["profile"]:
        raise RuntimeError("Incompatible cached pins or profile")
    old = {entry["source"]: entry["sha256"] for entry in previous["patches"]}
    new = {entry["source"]: entry["sha256"] for entry in state["patches"]}
    changed = {name for name in old.keys() | new.keys() if old.get(name) != new.get(name)}
    packages = set()
    if any(name.startswith("linux/") for name in changed):
        packages.update(["linux", "media_modules-aml"])
    if any(name.startswith("media/") for name in changed):
        packages.add("media_modules-aml")
    if previous.get("source_downloads") != state.get("source_downloads"):
        packages.add("keyutils")
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


def install(repo, profile):
    if profile not in PROFILES:
        raise ValueError("Unknown profile")
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    if head != PINS["coreelec"]:
        raise RuntimeError(f"Refusing unpinned checkout: {head}")
    validate_packages(repo)
    source_path, source_content, source_metadata = keyutils_download_fix(repo)
    options = PORT / "boards/usb-build.options"
    option_content = options.read_text() if profile == "decoder" else None
    option_destination = repo / ".coreelec/options"
    option_metadata = dict(destination=".coreelec/options", sha256=hashlib.sha256(option_content.encode()).hexdigest()) if option_content else None
    entries = []
    for relative in PROFILES[profile]:
        source = PORT / "patches" / relative
        dest_dir = LINUX_DIR if relative.startswith("linux/") else MEDIA_DIR
        destination = repo / dest_dir / ("9000-e900-" + source.name)
        entries.append(dict(source=relative, destination=str(destination.relative_to(repo)),
                            sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
    state = dict(profile=profile, pins=PINS, patches=entries, source_downloads=[source_metadata],
                 build_options=option_metadata, board_dtb=BOARD if profile == "decoder" else None,
                 status="experimental-unvalidated")
    marker = repo / ".e900-profile.json"
    previous = json.loads(marker.read_text()) if marker.exists() else None
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
    (repo / source_path).write_text(source_content)
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
