#!/usr/bin/env python3
"""Replace the pinned CE Image entry with an isolated marker + firmware reset."""
import argparse
import hashlib
import importlib.util
import json
import pathlib
import struct
import subprocess
import tempfile

PORT = pathlib.Path(__file__).resolve().parents[1]


def text_section(elf):
    assert elf[:6] == b"\x7fELF\x02\x01" and struct.unpack_from("<H", elf, 18)[0] == 183
    table = struct.unpack_from("<Q", elf, 40)[0]
    size, count, strings_index = struct.unpack_from("<3H", elf, 58)
    sections = [struct.unpack_from("<IIQQQQIIQQ", elf, table + i * size) for i in range(count)]
    names = sections[strings_index]
    strings = elf[names[4]:names[4] + names[5]]
    found = []
    for section in sections:
        name = strings[section[0]:strings.index(0, section[0])]
        if name == b".text":
            found.append(elf[section[4]:section[4] + section[5]])
        if section[1] in {4, 9}:
            assert section[5] == 0, "Unresolved reset-stub relocation"
    assert len(found) == 1
    return found[0]


def make(image, destination, clang):
    spec = importlib.util.spec_from_file_location("entry_trace", PORT / "scripts/make-entry-trace.py")
    trace = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trace)
    original = image.read_bytes()
    trace.instrument(original)  # Enforce exact pin and validate the original header.
    source = PORT / "boards/e900-entry-reset.S"
    with tempfile.TemporaryDirectory(prefix="e900-reset-stub-") as temporary:
        obj = pathlib.Path(temporary) / "reset.o"
        subprocess.run([clang, "-target", "aarch64-none-elf", "-c", str(source), "-o", str(obj)], check=True)
        stub = text_section(obj.read_bytes())
    assert len(stub) == 64
    assert stub[48:56] == struct.pack("<Q", 0x074ff000)
    assert stub[56:64] == struct.pack("<II", 0xe9080001, 0)
    assert struct.unpack_from("<I", stub, 36)[0] == 0xd4000003  # smc #0
    assert struct.unpack_from("<I", stub, 40)[0] == 0xd503205f  # wfe
    assert trace.branch_target(44, struct.unpack_from("<I", stub, 44)[0]) == 40
    assert len(original) + len(stub) <= struct.unpack_from("<Q", original, 16)[0]
    result = bytearray(original + stub)
    struct.pack_into("<I", result, 0, trace.branch(0, len(original)))
    assert result[4:len(original)] == original[4:]
    assert not destination.exists()
    destination.mkdir(parents=True)
    (destination / "e900-Image-reset").write_bytes(result)
    (destination / "E9RSEED.BIN").write_bytes(struct.pack("<II", 0xe9080000, 0))
    (destination / "reset-image-provenance.json").write_text(json.dumps(dict(
        image_sha256=hashlib.sha256(result).hexdigest(), original_image_sha256=trace.PINNED_IMAGE,
        stub_sha256=hashlib.sha256(stub).hexdigest(), stub_offset=len(original),
        reset_smc="0x84000009, x1..x3 zero; confirmed by live Android DT sys_reset + smc method",
        executes_linux_initialization=False, hardware_tested=False), indent=2) + "\n")
    print("Prepared isolated 64-byte ARM64 entry/reset stub:", destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=pathlib.Path)
    parser.add_argument("destination", type=pathlib.Path)
    parser.add_argument("--clang", default="clang")
    args = parser.parse_args()
    make(args.image, args.destination, args.clang)
