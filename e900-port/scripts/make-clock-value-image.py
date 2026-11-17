#!/usr/bin/env python3
"""Capture DI's clock handle without dereferencing it, then request reset."""
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
    spec = importlib.util.spec_from_file_location(name, PORT / "scripts" / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make(original_path, output):
    trace = load("clock_trace", "make-entry-trace.py")
    reset = load("clock_reset", "make-reset-entry-image.py")
    original = original_path.read_bytes()
    assert hashlib.sha256(original).hexdigest() == trace.PINNED_IMAGE
    with tempfile.TemporaryDirectory(prefix="e900-clock-value-") as temporary:
        obj = pathlib.Path(temporary) / "clock.o"
        subprocess.run(["clang", "-target", "aarch64-none-elf", "-c", str(PORT / "boards/e900-clock-value.S"), "-o", str(obj)], check=True)
        stub = reset.text_section(obj.read_bytes())
    assert len(stub) == 148 and struct.unpack_from("<I", stub, 24)[0] == 0xf940466c
    assert struct.unpack_from("<I", original, 0xcd4dfc)[0] == 0xf9404677
    assert struct.unpack_from("<Q", stub, 120)[0] == 0x1876000 - 0xcf1350
    assert struct.unpack_from("<I", stub, 128)[0] == 0xe9230001
    assert stub[132:] == b"0123456789abcdef"
    image = bytearray(original)
    image[0xcf1350:0xcf1350 + len(stub)] = stub
    struct.pack_into("<I", image, 0xcd4dfc, trace.branch(0xcd4dfc, 0xcf1350))
    assert image[:0xcd4dfc] == original[:0xcd4dfc]
    assert image[0xcd4e00:0xcf1350] == original[0xcd4e00:0xcf1350]
    assert image[0xcf1350 + len(stub):] == original[0xcf1350 + len(stub):]
    assert not output.exists()
    output.mkdir(parents=True)
    (output / "e900-Image-clock").write_bytes(image)
    (output / "E9RSEED.BIN").write_bytes(struct.pack("<II", 0xe9230000, 0))
    (output / "image-provenance.json").write_text(json.dumps(dict(
        original_sha256=trace.PINNED_IMAGE, image_sha256=hashlib.sha256(image).hexdigest(),
        hook=0xcd4dfc, stub_bytes=len(stub), hardware_tested=False), indent=2) + "\n")
    print("Prepared clock pointer snapshot:", output)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("original", type=pathlib.Path)
    p.add_argument("output", type=pathlib.Path)
    args = p.parse_args()
    make(args.original, args.output)
