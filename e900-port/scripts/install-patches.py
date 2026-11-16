#!/usr/bin/env python3
"""Install a version-checked patch profile into a dedicated CoreELEC checkout."""
import hashlib
import json
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
PROFILES["decoder"] = PROFILES["hdmi"] + ["media/0002-gxlx2-experimental-clock-registration.patch"]


def validate_packages(repo):
    for relative, key in [
        ("projects/Amlogic-ce/packages/linux/package.mk", "linux"),
        ("projects/Amlogic-ce/packages/linux-drivers/amlogic/media_modules-aml/package.mk", "media_modules"),
    ]:
        content = (repo / relative).read_text()
        if not re.search(r'PKG_VERSION="' + PINS[key] + '"', content):
            raise RuntimeError(f"Unexpected package revision: {relative}")


def install(repo, profile):
    if profile not in PROFILES:
        raise ValueError("Unknown profile")
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    if head != PINS["coreelec"]:
        raise RuntimeError(f"Refusing unpinned checkout: {head}")
    validate_packages(repo)
    entries = []
    for relative in PROFILES[profile]:
        source = PORT / "patches" / relative
        dest_dir = LINUX_DIR if relative.startswith("linux/") else MEDIA_DIR
        destination = repo / dest_dir / ("9000-e900-" + source.name)
        entries.append(dict(source=relative, destination=str(destination.relative_to(repo)),
                            sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
    state = dict(profile=profile, pins=PINS, patches=entries,
                 status="uncompiled-unvalidated-board-dtb-not-integrated")
    marker = repo / ".e900-profile.json"
    previous = json.loads(marker.read_text()) if marker.exists() else None
    if previous and previous != state and any(repo.glob("build.*")):
        raise RuntimeError("Patch profile changed after building. Use a fresh build volume "
                           "or explicitly clean the affected packages before updating patches.")
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
    marker.write_text(json.dumps(state, indent=2) + "\n")
    print(f"Profile {profile}: {len(entries)} candidate patches installed; no board DTB installed.")


if __name__ == "__main__":
    try:
        install(pathlib.Path(sys.argv[1]).resolve(), sys.argv[2])
    except (RuntimeError, ValueError, IndexError) as exc:
        sys.exit(str(exc))
