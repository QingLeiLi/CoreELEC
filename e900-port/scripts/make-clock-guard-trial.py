#!/usr/bin/env python3
"""Controlled missing-clock guard trial; valid-clock path remains unchanged."""
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
    trace = load("guard_trace", "make-entry-trace.py")
    reset = load("guard_reset", "make-reset-entry-image.py")
    original = original_path.read_bytes()
    assert hashlib.sha256(original).hexdigest() == trace.PINNED_IMAGE
    # Linker padding after __idmap_text_end, below _etext. The earlier
    # slot 0xcf1350 was __cpu_soft_restart and must remain intact.
    scratch, hook = 0xcfff00, 0xcd4e04
    assert original[scratch:scratch + 28] == bytes(28)
    assert struct.unpack_from("<I", original, hook)[0] == 0x97dfbc37
    delta = 0xcd4e08 - (scratch + 12)
    assert -(1 << 20) <= delta < (1 << 20)
    adr = 0x1000001e | ((delta & 3) << 29) | (((delta >> 2) & 0x7ffff) << 5)
    defines = dict(E9_RETURN_ADR=adr, E9_ORIGINAL_CALL=trace.branch(scratch + 16, 0x4c3ee0),
                   E9_SKIP_BRANCH=trace.branch(scratch + 24, 0xcd4e2c))
    with tempfile.TemporaryDirectory(prefix="e900-clock-guard-") as temporary:
        obj = pathlib.Path(temporary) / "guard.o"
        subprocess.run(["clang", "-target", "aarch64-none-elf", *[f"-D{k}={hex(v)}" for k, v in defines.items()],
                        "-c", str(PORT / "boards/e900-clock-guard.S"), "-o", str(obj)], check=True)
        stub = reset.text_section(obj.read_bytes())
    assert len(stub) == 28
    words = struct.unpack("<7I", stub)
    assert words[3] == adr and trace.branch_target(scratch + 16, words[4]) == 0x4c3ee0
    assert words[5] == 0xf900467f and trace.branch_target(scratch + 24, words[6]) == 0xcd4e2c
    image = bytearray(original)
    image[scratch:scratch + len(stub)] = stub
    struct.pack_into("<I", image, hook, trace.branch(hook, scratch))
    assert image[:hook] == original[:hook] and image[hook + 4:scratch] == original[hook + 4:scratch]
    assert image[scratch + len(stub):] == original[scratch + len(stub):]
    assert not output.exists()
    output.mkdir(parents=True)
    (output / "e900-Image-guard").write_bytes(image)
    (output / "E9RSEED.BIN").write_bytes(struct.pack("<II", 0xe9240000, 0))
    (output / "guard-provenance.json").write_text(json.dumps(dict(
        original_sha256=trace.PINNED_IMAGE, image_sha256=hashlib.sha256(image).hexdigest(),
        hook=hook, scratch=scratch, instructions=[hex(w) for w in words],
        trial="NULL/ERR_PTR clock guard only; not final GXLX2 clock adaptation",
        zero_padding_stub=True, cpu_soft_restart_preserved=True, hardware_tested=False), indent=2) + "\n")
    print("Prepared missing-clock guard trial:", output)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("original", type=pathlib.Path)
    p.add_argument("output", type=pathlib.Path)
    a = p.parse_args()
    make(a.original, a.output)
