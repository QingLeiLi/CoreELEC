#!/usr/bin/env python3
"""Cache identities and selective invalidation for the pinned CoreELEC build."""
import hashlib
import importlib.util
import json
import os
import pathlib
import subprocess
import sys

PORT = pathlib.Path(__file__).resolve().parents[1]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:24]


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identities(port, profile, work_root, host):
    spec = importlib.util.spec_from_file_location("cache_installer", port / "scripts/install-patches.py")
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    if profile not in installer.PROFILES:
        raise ValueError("Unknown profile")
    pins = json.loads((port / "pins.json").read_text())
    compatibility = dict(schema=1, pins=pins, host=host, profile=profile,
                         source_root=str((work_root / ("CoreELEC-" + profile)).resolve()),
                         project="Amlogic-ce", device="Amlogic-ng", arch="arm",
                         build_script=file_hash(port / "scripts/build.sh"),
                         setup_script=file_hash(port / "scripts/ci-dependencies.sh"))
    state = dict(patches={name: file_hash(port / "patches" / name)
                          for name in installer.PROFILES[profile]},
                 installer=file_hash(port / "scripts/install-patches.py"),
                 cache_protocol=file_hash(port / "scripts/build-cache.py"))
    return dict(compat=digest(compatibility), state=digest(state),
                compiler=digest(dict(schema=1, pins=pins, host=host)),
                details=compatibility)


def host_identity():
    packages = subprocess.check_output([
        "dpkg-query", "-W", "-f=${binary:Package}=${Version}\n",
        "gcc-12", "g++-12", "libc6", "libstdc++6", "zlib1g", "libssl3"], text=True)
    return dict(os_release=pathlib.Path("/etc/os-release").read_text(),
                machine=os.uname().machine, packages=packages)


def invalidate(repo):
    pending = repo / ".e900-invalidate.json"
    if not pending.exists():
        return
    packages = json.loads(pending.read_text())
    if not isinstance(packages, list) or any(name not in {"linux", "media_modules-aml", "keyutils"}
                                           for name in packages):
        raise ValueError("Unexpected package in cache invalidation plan")
    # Use the buildsystem's cleaner; never remove the shared toolchain directory.
    for package in sorted(set(packages), key=lambda name: name == "linux"):
        subprocess.run(["bash", "./scripts/clean", package], cwd=repo, check=True)
    pending.unlink()


def main():
    command = sys.argv[1]
    if command == "invalidate":
        invalidate(pathlib.Path(sys.argv[2]).resolve())
    elif command == "keys":
        work = pathlib.Path(os.environ["E900_WORK_ROOT"])
        result = identities(PORT, os.environ["PROFILE"], work, host_identity())
        work.mkdir(parents=True, exist_ok=True)
        (work / "cache-identity.json").write_text(json.dumps(result, indent=2) + "\n")
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            for name in ["compat", "state", "compiler"]:
                output.write(f"{name}={result[name]}\n")
        print(json.dumps(result, indent=2))
    else:
        raise ValueError("Unknown command")


if __name__ == "__main__":
    main()
