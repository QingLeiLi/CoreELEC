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

# These exact setup scripts differ only by installing squashfs-tools, a host
# image inspection tool. Compiler versions/ISA/root/profile must still match.
# Unknown future setup changes get no fallback; never broaden the cache prefix.
PREVIOUS_COMPATIBLE_SETUP = {
    "13d79da29b8569e6a65d2febca7a7f951ef3de768b4db2c32ded8bd4a54a67e0":
        "1d97a8f262f0945e8c6d5a3db9ac2c151ab54140770df5d5a297efc9203f1db4",
}


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
    compatibility = dict(schema=2, pins=pins, host=host, profile=profile,
                         host_codegen=installer.HOST_CODEGEN,
                         source_root=str((work_root / ("CoreELEC-" + profile)).resolve()),
                         project="Amlogic-ce", device="Amlogic-ng", arch="arm",
                         build_script=file_hash(port / "scripts/build.sh"),
                         setup_script=file_hash(port / "scripts/ci-dependencies.sh"))
    state = dict(patches={name: file_hash(port / "patches" / name)
                          for name in installer.selected_patches(profile)},
                 image_files=installer.image_overlay_metadata(profile),
                 installer=file_hash(port / "scripts/install-patches.py"),
                 board_options=file_hash(port / "boards/usb-build.options") if profile == "decoder" else None,
                 cache_protocol=file_hash(port / "scripts/build-cache.py"))
    previous_setup = PREVIOUS_COMPATIBLE_SETUP.get(compatibility["setup_script"])
    previous_compat = digest(dict(compatibility, setup_script=previous_setup)) if previous_setup else "none"
    return dict(compat=digest(compatibility), previous_compat=previous_compat, state=digest(state),
                compiler=digest(dict(schema=2, pins=pins, host=host, host_codegen=installer.HOST_CODEGEN)),
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
    if not isinstance(packages, list) or "toolchain" in packages:
        raise ValueError("Unexpected package in cache invalidation plan")
    # Use the buildsystem's cleaner; never remove the shared toolchain directory.
    # Keep Linux last, and make other packages independent of set/hash order.
    for package in sorted(set(packages), key=lambda name: (name == "linux", name)):
        subprocess.run(["bash", "./scripts/clean", package], cwd=repo, check=True)
    pending.unlink()


def main():
    command = sys.argv[1]
    if command == "invalidate":
        invalidate(pathlib.Path(sys.argv[2]).resolve())
    elif command == "keys":
        work = pathlib.Path(os.environ["E900_WORK_ROOT"])
        result = identities(PORT, os.environ["PROFILE"], work, host_identity())
        # CPU diagnostics are deliberately outside the key: host objects now use
        # a fixed generic ISA, so different runner CPU models may share them.
        cpuinfo = pathlib.Path("/proc/cpuinfo")
        observed_cpu = {}
        if cpuinfo.exists():
            for line in cpuinfo.read_text().splitlines():
                key, separator, value = line.partition(":")
                if separator and key.strip() in {"vendor_id", "model name", "flags"}:
                    observed_cpu.setdefault(key.strip(), value.strip())
        result["observed_cpu"] = observed_cpu
        work.mkdir(parents=True, exist_ok=True)
        (work / "cache-identity.json").write_text(json.dumps(result, indent=2) + "\n")
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            for name in ["compat", "previous_compat", "state", "compiler"]:
                output.write(f"{name}={result[name]}\n")
        print(json.dumps(result, indent=2))
    else:
        raise ValueError("Unknown command")


if __name__ == "__main__":
    main()
