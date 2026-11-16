#!/usr/bin/env python3
"""Build a USB-only bootloader probe that returns to the existing Android boot."""
import argparse
import hashlib
import importlib.util
import json
import pathlib
import secrets
import shutil
import subprocess
import zipfile

PORT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("usb_probe_format", PORT / "scripts/prepare-usb-image.py")
usb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(usb)


def make(destination, mkimage):
    if destination.exists() or destination.with_suffix(".zip").exists():
        raise ValueError("Probe output already exists")
    source = PORT / "boards/e900-usb-probe.src"
    # Keep this capability test independent of kernel, MMIO and stored env changes.
    for forbidden in ["saveenv", "defenv", "bootm", "booti", "mw.", "mmc write", "store write", "reset"]:
        assert forbidden not in source.read_text(), forbidden
    destination.mkdir(parents=True)
    marker = f"E900 USB bootloader probe reached. nonce={secrets.token_hex(8)}\n".encode()
    (destination / "E9INPUT.TXT").write_bytes(marker)
    script = destination / "s905_autoscript"
    subprocess.run([str(mkimage), "-A", "arm", "-O", "linux", "-T", "script", "-C", "none",
                    "-n", "E900 bootloader probe", "-d", str(source), str(script)], check=True)
    usb.check_script(script, source.read_bytes())
    for name in ["aml_autoscript", "cfgload"]:
        shutil.copy2(script, destination / name)
    (destination / "probe-provenance.json").write_text(json.dumps(dict(
        mode="bootloader-only; no CE kernel call", expected_marker=marker.decode().strip(),
        marker_sha256=hashlib.sha256(marker).hexdigest(), script_source_sha256=usb.sha256(source),
        writes="E9PROBE.TXT on the USB drive containing E9INPUT.TXT only", hardware_tested=False), indent=2) + "\n")
    (destination / "README.txt").write_text(
        "Power off. Copy FOUR files to the existing COREELEC FAT root:\n"
        "E9INPUT.TXT, aml_autoscript, s905_autoscript, cfgload. Overwrite the three scripts.\n"
        "Remove an old E9PROBE.TXT before testing, if present. Keep all kernel/SYSTEM files.\n"
        "Boot with USB attached. The script pauses for 12 seconds, then returns to existing boot.\n"
        "It does not start CE, write eMMC, change persistent environment or access MMIO.\n"
        "If FAT write works, E9PROBE.TXT will match E9INPUT.TXT exactly.\n"
        "Missing output alone cannot distinguish an unread script from unavailable FAT write.\n")
    archive = destination.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for path in destination.iterdir():
            output.write(path, path.name)
    print(f"Prepared bootloader-only probe: {archive}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=pathlib.Path)
    parser.add_argument("--mkimage", type=pathlib.Path, required=True)
    args = parser.parse_args()
    make(args.destination.resolve(), args.mkimage.resolve())
