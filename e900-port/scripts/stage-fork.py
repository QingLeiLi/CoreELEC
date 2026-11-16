#!/usr/bin/env python3
"""Copy only public development files into a fresh pinned CoreELEC fork checkout."""
import json
import pathlib
import shutil
import subprocess
import sys

source = pathlib.Path(__file__).resolve().parents[1]
repo = pathlib.Path(sys.argv[1]).resolve()
pin = json.loads((source / "pins.json").read_text())["coreelec"]
head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
if head != pin:
    raise SystemExit("Stage into a fresh checkout of the pinned CoreELEC revision.")
destination = repo / "e900-port"
allowed_files = [".gitignore", ".gitattributes", "Dockerfile", "README.md", "CLOUD.md", "pins.json"]
allowed_dirs = ["boards", "patches", "scripts", "tests"]
for name in allowed_files:
    target = destination / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / name, target)
for name in allowed_dirs:
    for item in (source / name).rglob("*"):
        if not item.is_file() or item.is_symlink() or "__pycache__" in item.parts:
            continue
        relative = item.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
workflow = repo / ".github/workflows/e900-coreelec.yml"
workflow.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(source / ".github/workflows/e900-coreelec.yml", workflow)
print(f"Staged public files in {destination}; local firmware, backups and credentials excluded.")
