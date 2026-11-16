#!/usr/bin/env python3
"""Copy build outputs and provenance into the persistent Linux work volume."""
import hashlib
import importlib.util
import json
import os
import pathlib
import shutil
import sys

repo = pathlib.Path(sys.argv[1]).resolve()
profile = sys.argv[2]
if profile not in {"baseline", "identify", "hdmi", "decoder"}:
    raise SystemExit("Unknown profile")
work_root = pathlib.Path(os.environ.get("E900_WORK_ROOT", "/work"))
dest = work_root / "export" / profile
dest.mkdir(parents=True, exist_ok=True)
state = json.loads((repo / ".e900-profile.json").read_text())
state["status"] = "experimental-not-hardware-validated"
state["last_action"] = sys.argv[3]
state["last_action_exit_code"] = int(sys.argv[4])
artifacts = []
paths = []
state["usb_image_prepared"] = False
marker = repo / ".e900-usb-image.json"
if state["last_action"] == "image" and state["last_action_exit_code"] == 0 and marker.exists():
    spec = importlib.util.spec_from_file_location("usb_image", pathlib.Path(__file__).with_name("prepare-usb-image.py"))
    usb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(usb)
    prepared = json.loads(marker.read_text())
    relative = pathlib.Path(prepared["image"])
    if relative.is_absolute() or ".." in relative.parts or relative.parent != pathlib.Path("target"):
        raise ValueError("Unexpected prepared image path")
    image = repo / relative
    if (prepared["run_id"] == os.environ.get("GITHUB_RUN_ID", "local")
            and prepared["run_attempt"] == os.environ.get("GITHUB_RUN_ATTEMPT", "local")
            and prepared["profile_state_sha256"] == usb.sha256(repo / ".e900-profile.json")
            and prepared["boot_script_sha256"] == usb.sha256(usb.PORT / "boards/e900-usb-autoscript.src")
            and prepared["sha256"] == usb.sha256(image)
            and prepared["board"]["sha256"] == usb.board.validate(usb.board.find_board(repo))["sha256"]):
        paths.extend([image, image.with_name(image.name + ".sha256"), image.with_name(image.name + ".json")])
        state["usb_image_prepared"] = True
        state["usb_image"] = prepared
# The export folder may survive local retries. Remove only previously recorded
# regular files inside our target export, so a failed run cannot offer an old image.
old_metadata = dest / "build-metadata.json"
if old_metadata.exists():
    for entry in json.loads(old_metadata.read_text()).get("artifacts", []):
        relative = pathlib.Path(entry["path"])
        if not relative.is_absolute() and ".." not in relative.parts and relative.parts[0] == "target":
            old = dest / relative
            if old.is_file() and not old.is_symlink():
                old.unlink()

paths.extend(repo.glob("build.*/build/media_modules-aml-*/drivers/**/*.ko"))
for build in repo.glob("build.*/build/linux-*"):
    paths.extend(build.glob("arch/arm64/boot/Image*"))
    paths.extend(build.glob(".config"))
    paths.extend(build.glob("arch/arm64/boot/dts/amlogic/coreelec-gxl/gxlx2_p291_1g_e900v21c.dtb"))
for source in paths:
    if not source.is_file() or source.is_symlink():
        continue
    relative = source.relative_to(repo)
    target = dest / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    artifacts.append(dict(path=str(relative), sha256=digest.hexdigest(), size=source.stat().st_size))
state["artifacts"] = artifacts
(dest / "build-metadata.json").write_text(json.dumps(state, indent=2) + "\n")
(dest / "NOT-READY-TO-FLASH.txt").unlink(missing_ok=True)
(dest / "USB-TEST-STATUS.txt").write_text(
    "Experimental build output. Hardware validation remains pending.\n"
    f"Prepared USB test image in this run: {state['usb_image_prepared']}\n"
    "Only a prepared *-E900V21C-USB-TEST.img.gz is intended for external USB testing.\n"
    "Do not install to eMMC or use generic target output as a board image.\n")
logs = dest / "logs"
logs.mkdir(exist_ok=True)
for source in (work_root / "logs").glob(profile + "-*.log"):
    shutil.copy2(source, logs / source.name)
print(f"Exported {len(artifacts)} artifacts to {dest}")
