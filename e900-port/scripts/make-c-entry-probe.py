#!/usr/bin/env python3
"""Patch only the pinned C entry and an isolated identity-page reset stub."""
import argparse
import hashlib
import importlib.util
import json
import pathlib
import struct
import subprocess
import tempfile

PORT = pathlib.Path(__file__).resolve().parents[1]


def load(name, file):
    s = importlib.util.spec_from_file_location(name, PORT / "scripts" / file)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def make(original_path, output):
    trace = load("c_trace", "make-entry-trace.py")
    reset = load("c_reset", "make-reset-entry-image.py")
    original = original_path.read_bytes()
    assert hashlib.sha256(original).hexdigest() == trace.PINNED_IMAGE
    hook, scratch = 0x12b07c8, 0xcf1350
    assert struct.unpack_from("<4I", original, hook) == (0xa9bb7bfd, 0xb0002ea0, 0x91260000, 0x910003fd)
    assert trace.branch_target(0x12b0210, struct.unpack_from("<I", original, 0x12b0210)[0]) == hook
    with tempfile.TemporaryDirectory(prefix="e900-c-entry-") as t:
        obj = pathlib.Path(t) / "stub.o"
        subprocess.run(["clang", "-target", "aarch64-none-elf", "-c", str(PORT / "boards/e900-c-entry-reset.S"), "-o", str(obj)], check=True)
        stub = reset.text_section(obj.read_bytes())
    assert len(stub) == 128 and scratch + len(stub) < 0xcf1430
    assert scratch // 4096 == (scratch + len(stub) - 1) // 4096
    assert stub[-16:] == struct.pack("<QII", trace.TRACE, 0xe9120001, 0)
    modified = bytearray(original)
    modified[scratch:scratch + len(stub)] = stub
    struct.pack_into("<I", modified, hook, trace.branch(hook, scratch))
    assert modified[:64] == original[:64]
    assert modified[:scratch] == original[:scratch]
    assert modified[scratch + len(stub):hook] == original[scratch + len(stub):hook]
    assert modified[hook + 4:] == original[hook + 4:]
    assert not output.exists()
    output.mkdir(parents=True)
    (output / "e900-Image-cstart").write_bytes(modified)
    (output / "E9RSEED.BIN").write_bytes(struct.pack("<II", 0xe9120000, 0))
    (output / "c-entry-provenance.json").write_text(json.dumps(dict(
        original_sha256=trace.PINNED_IMAGE, image_sha256=hashlib.sha256(modified).hexdigest(),
        hook=hook, scratch=scratch, stub_bytes=len(stub),
        scratch_original_sha256=hashlib.sha256(original[scratch:scratch + len(stub)]).hexdigest(),
        milestone="start_kernel entry before first C prologue instruction",
        limitations="Marker absence also permits diagnostic stub failure. Scratch code is never used for normal kernel continuation.",
        hardware_tested=False), indent=2) + "\n")
    print("Prepared C-entry probe", output)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("original", type=pathlib.Path)
    p.add_argument("output", type=pathlib.Path)
    a = p.parse_args()
    make(a.original, a.output)
