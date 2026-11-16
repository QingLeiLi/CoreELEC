#!/usr/bin/env python3
"""Copy build outputs and provenance into the persistent Linux work volume."""
import hashlib
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
state["status"] = "experimental-not-hardware-validated-board-dtb-not-integrated"
state["last_action"] = sys.argv[3]
state["last_action_exit_code"] = int(sys.argv[4])
artifacts = []
paths = list((repo / "target").glob("*"))
paths.extend(repo.glob("build.*/media_modules-aml-*/drivers/**/*.ko"))
for build in repo.glob("build.*/linux-*"):
    paths.extend(build.glob("arch/arm64/boot/Image*"))
    paths.extend(build.glob(".config"))
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
(dest / "NOT-READY-TO-FLASH.txt").write_text(
    "Experimental build output. E900V21C board DTB is not integrated.\n"
    "Compilation and hardware validation must be recorded separately.\n"
    "Do not install to eMMC or assume generic image output supports this board.\n")
logs = dest / "logs"
logs.mkdir(exist_ok=True)
for source in (work_root / "logs").glob(profile + "-*.log"):
    shutil.copy2(source, logs / source.name)
print(f"Exported {len(artifacts)} artifacts to {dest}")
