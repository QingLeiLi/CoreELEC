#!/usr/bin/env python3
"""Instrument the pinned, verified Image entry; no new kernel build or flash."""
import argparse
import hashlib
import importlib.util
import json
import pathlib
import shutil
import struct
import subprocess
import zipfile

PORT = pathlib.Path(__file__).resolve().parents[1]
TRACE = 0x074ff000
ARMED, ENTERED = 0xe9000000, 0xe9000001
PINNED_IMAGE = "7fb0bec24765a79267a30420b817c9d9063a1043eba04b3fe77ac98d6c1be6cf"
PINNED_DTB = "a6d547b1f883a42ce0fdab84946b18d01a7915b8e2cff4f2b1c8f371907708fd"
PINNED_INITRD = "4fc9c4036c03d6ed64366957cb690e554eb87cffacc8e406d1546e48881951e2"


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, PORT / "scripts" / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def branch(origin, destination):
    delta = destination - origin
    assert delta % 4 == 0 and -(1 << 27) <= delta < (1 << 27)
    return 0x14000000 | ((delta // 4) & 0x03ffffff)


def branch_target(origin, instruction):
    assert instruction & 0xfc000000 == 0x14000000
    offset = instruction & 0x03ffffff
    if offset & 0x02000000:
        offset -= 0x04000000
    return origin + offset * 4


def instrument(original):
    assert hashlib.sha256(original).hexdigest() == PINNED_IMAGE
    assert original[56:60] == b"ARMd" and len(original) % 8 == 0
    target = branch_target(0, struct.unpack_from("<I", original)[0])
    assert 64 <= target < len(original)
    start = len(original)
    # x0..x3 (including DTB pointer) remain untouched. x16/x17 are scratch
    # registers at ARM64 kernel entry. Literals are position independent.
    words = [0x580000d0, 0x180000f1, 0xb9000211, 0xd5033f9f,
             branch(start + 16, target), 0xd503201f]
    trampoline = struct.pack("<6IQII", *words, TRACE, ENTERED, 0)
    result = bytearray(original + trampoline)
    struct.pack_into("<I", result, 0, branch(0, start))
    assert branch_target(0, struct.unpack_from("<I", result)[0]) == start
    assert branch_target(start + 16, words[4]) == target
    assert len(result) <= struct.unpack_from("<Q", original, 16)[0]
    assert result[4:len(original)] == original[4:]
    return bytes(result), dict(trampoline_offset=start, original_entry_target=target,
                               words=[f"{word:08x}" for word in words])


def make(kit, destination, mkimage):
    usb = module("entry_usb", "prepare-usb-image.py")
    booti = module("entry_booti", "make-booti-test-kit.py")
    assert not destination.exists() and not destination.with_suffix(".zip").exists()
    original = (kit / "e900-Image").read_bytes()
    traced, report = instrument(original)
    dtb = (kit / "dtb.img").read_bytes()
    assert hashlib.sha256(dtb).hexdigest() == PINNED_DTB
    usb.board.validate(kit / "dtb.img")
    nodes = usb.board.read_fdt(dtb)
    reserved = "/reserved-memory/ramoops@0x07400000"
    assert usb.board.cells(nodes[reserved]["reg"]) == [0, 0x07400000, 0, 0x100000]
    assert dtb.count(b"ramoops\0") == 1
    # Keep the exact reservation while preventing ramoops from overwriting the
    # trace. Both property values are eight bytes, so FDT offsets stay intact.
    traced_dtb = dtb.replace(b"ramoops\0", b"e9trace\0")
    new_nodes = usb.board.read_fdt(traced_dtb)
    assert new_nodes[reserved]["compatible"] == b"e9trace\0"
    for name in nodes:
        for key, value in nodes[name].items():
            if (name, key) != (reserved, "compatible"):
                assert new_nodes[name][key] == value
    import gzip
    initrd = kit / "e900-uInitrd"
    compressed = initrd.read_bytes()[64:]
    booti.legacy_image(initrd, 3, 1, compressed)
    assert hashlib.sha256(gzip.decompress(compressed)).hexdigest() == PINNED_INITRD
    destination.mkdir(parents=True)
    (destination / "e900-Image-trace").write_bytes(traced)
    (destination / "e900-trace.dtb").write_bytes(traced_dtb)
    (destination / "E9ARM.BIN").write_bytes(struct.pack("<II", ARMED, 0))
    source = PORT / "boards/e900-usb-entry-trace.src"
    for forbidden in ["saveenv", "defenv", "mmc write", "store write", "reset", "mw."]:
        assert forbidden not in source.read_text(), forbidden
    script = destination / "s905_autoscript"
    subprocess.run([str(mkimage), "-A", "arm", "-O", "linux", "-T", "script", "-C", "none",
                    "-n", "E900 ARM64 entry trace", "-d", str(source), str(script)], check=True)
    usb.check_script(script, source.read_bytes())
    for name in ["aml_autoscript", "cfgload"]:
        shutil.copy2(script, destination / name)
    report.update(original_image_sha256=PINNED_IMAGE, original_dtb_sha256=PINNED_DTB,
                  trace_address=TRACE, armed=ARMED, entered=ENTERED, hardware_tested=False,
                  limitations="Warm-reset RAM retention and USB script reexecution are not guaranteed. "
                              "Entry marker is before normal Linux initialization; no marker is inconclusive.")
    (destination / "trace-provenance.json").write_text(json.dumps(report, indent=2) + "\n")
    (destination / "README.txt").write_text(
        "Copy six files to existing CE USB: e900-Image-trace, e900-trace.dtb, E9ARM.BIN, three scripts.\n"
        "Keep the previously verified e900-uInitrd and SYSTEM. No eMMC/env writes.\n"
        "Normal files are preserved; copy preflight-03 scripts to roll back.\n"
        "A cold boot attempts CE only if RAM marker load/readback succeeds.\n"
        "On a warm reset, retained marker returns to Android: e9_entry=reached or not_observed.\n"
        "RAM retention is not guaranteed. If two reset cycles occur, remove USB and boot Android.\n"
        "Do not infer successful Linux initialization from an entry marker.\n")
    files = sorted(p for p in destination.iterdir() if p.is_file())
    (destination / "SHA256SUMS").write_text("".join(f"{usb.sha256(p)}  {p.name}\n" for p in files))
    with zipfile.ZipFile(destination.with_suffix(".zip"), "w", zipfile.ZIP_DEFLATED) as archive:
        for path in destination.iterdir():
            archive.write(path, path.name)
    print("Prepared", destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kit", type=pathlib.Path)
    parser.add_argument("destination", type=pathlib.Path)
    parser.add_argument("--mkimage", type=pathlib.Path, required=True)
    args = parser.parse_args()
    make(args.kit.resolve(), args.destination.resolve(), args.mkimage.resolve())
