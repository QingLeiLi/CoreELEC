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


def make(destination, mkimage, mode="write"):
    if destination.exists() or destination.with_suffix(".zip").exists():
        raise ValueError("Probe output already exists")
    source = PORT / "boards" / {"write": "e900-usb-probe.src", "capabilities": "e900-usb-capabilities.src",
                               "preflight": "e900-usb-preflight.src"}[mode]
    # Keep this capability test independent of kernel, MMIO and stored env changes.
    for forbidden in ["saveenv", "defenv", "mw.", "mmc write", "store write", "reset"]:
        assert forbidden not in source.read_text(), forbidden
    if mode == "write":
        for forbidden in ["bootm", "booti"]:
            assert forbidden not in source.read_text(), forbidden
    elif mode == "capabilities":
        # Capability queries must never turn into a kernel launch or storage access.
        import re
        for line in source.read_text().splitlines():
            assert re.fullmatch(r'(echo .*|setenv .*|if help (booti|bootm|fatwrite|fdt); then setenv e9_\w+ present; fi)', line), line
    else:
        import re
        for line in source.read_text().splitlines():
            assert re.fullmatch(r'(echo .*|usb start|setenv .*|for e9dev in 0 1 2 3; do|done|\s*(if fatload usb \$\{e9dev\}:1 0x[0-9a-f]+ (E9INPUT.TXT|e900-Image|dtb.img|e900-uInitrd); then|if iminfo 0x15000000; then|setenv .*|else|fi))', line), line
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
        mode=mode, expected_marker=(marker.decode().strip() if mode == "write" else
                                   ("e9probe=cap02" if mode == "capabilities" else "e9probe=pre03") + " in /proc/cmdline"),
        marker_sha256=hashlib.sha256(marker).hexdigest(), script_source_sha256=usb.sha256(source),
        writes=("E9PROBE.TXT on the USB drive containing E9INPUT.TXT only" if mode == "write" else "RAM environment only; no persistent writes"), hardware_tested=False), indent=2) + "\n")
    (destination / "README.txt").write_text(
        "Power off. Copy FOUR files to the existing COREELEC FAT root:\n"
        "E9INPUT.TXT, aml_autoscript, s905_autoscript, cfgload. Overwrite the three scripts.\n"
        "Remove an old E9PROBE.TXT before testing, if present. Keep all kernel/SYSTEM files.\n"
        "Boot with USB attached. The script pauses for 12 seconds, then returns to existing boot.\n"
        "It does not start CE, write eMMC, change persistent environment or access MMIO.\n"
        "If FAT write works, E9PROBE.TXT will match E9INPUT.TXT exactly.\n"
        "Missing output alone cannot distinguish an unread script from unavailable FAT write.\n")
    if mode == "capabilities":
        (destination / "E9INPUT.TXT").unlink()
        (destination / "README.txt").write_text(
            "Copy aml_autoscript, s905_autoscript and cfgload to the existing USB FAT root.\n"
            "This probe only queries command help and modifies the RAM copy of bootargs.\n"
            "It starts no CE kernel and writes no storage or persistent environment.\n"
            "Cold boot with USB attached; after Android starts, read /proc/cmdline through ADB.\n"
            "Expect e9probe=cap02; help failures cannot establish command absence.\n"
            "Missing tags alone are inconclusive if subsequent firmware overwrites bootargs.\n")
    if mode == "preflight":
        (destination / "README.txt").write_text(
            "Copy E9INPUT.TXT and the three scripts to the existing CE USB FAT root.\n"
            "Keep e900-Image, e900-uInitrd and dtb.img from the verified booti kit.\n"
            "This probe loads files into RAM and checks the legacy initrd image using iminfo.\n"
            "It does not execute a CE kernel, change the active FDT or write persistent storage.\n"
            "After cold boot, read /proc/cmdline from Android: expect e9probe=pre03 and file sizes.\n"
            "Sizes use U-Boot hexadecimal notation. iminfo failure alone is inconclusive.\n")
    archive = destination.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for path in destination.iterdir():
            output.write(path, path.name)
    print(f"Prepared bootloader-only probe: {archive}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=pathlib.Path)
    parser.add_argument("--mkimage", type=pathlib.Path, required=True)
    parser.add_argument("--mode", choices=["write", "capabilities", "preflight"], default="write")
    args = parser.parse_args()
    make(args.destination.resolve(), args.mkimage.resolve(), args.mode)
