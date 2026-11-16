#!/usr/bin/env python3
"""Cross-check entry trampoline encoding against an independent ARM64 assembler."""
import argparse
import importlib.util
import pathlib
import struct
import subprocess
import tempfile

PORT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("trace", PORT / "scripts/make-entry-trace.py")
trace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("image", type=pathlib.Path)
parser.add_argument("--clang", default="clang")
args = parser.parse_args()
original = args.image.read_bytes()
patched, report = trace.instrument(original)
offset = report["trampoline_offset"]
target = report["original_entry_target"]
assembly = f""".text
  ldr x16, address
  ldr w17, marker
  str w17, [x16]
  dsb sy
  b . + ({target - offset - 16})
  nop
address: .quad {trace.TRACE}
marker: .word {trace.ENTERED}
  .word 0
"""
with tempfile.TemporaryDirectory(prefix="e900-entry-asm-") as temporary:
    source, obj = [pathlib.Path(temporary) / name for name in ["trace.S", "trace.o"]]
    source.write_text(assembly)
    subprocess.run([args.clang, "-target", "aarch64-none-elf", "-c", str(source), "-o", str(obj)], check=True)
    elf = obj.read_bytes()
    assert elf[:6] == b"\x7fELF\x02\x01" and struct.unpack_from("<H", elf, 18)[0] == 183
    table = struct.unpack_from("<Q", elf, 40)[0]
    size, count, strings_index = struct.unpack_from("<3H", elf, 58)
    sections = [struct.unpack_from("<IIQQQQIIQQ", elf, table + index * size) for index in range(count)]
    names_header = sections[strings_index]
    names = elf[names_header[4]:names_header[4] + names_header[5]]
    found = []
    for section in sections:
        name = names[section[0]:names.index(0, section[0])]
        if name == b".text":
            found.append(elf[section[4]:section[4] + section[5]])
        if section[1] in {4, 9}:
            assert section[5] == 0, "Unexpected assembler relocations"
    assert found == [patched[offset:]], "Hand-encoded instructions differ from Clang ARM64 output"
assert patched[4:len(original)] == original[4:]
assert trace.branch_target(0, struct.unpack_from("<I", patched)[0]) == offset
assert trace.branch_target(offset + 16, struct.unpack_from("<I", patched, offset + 16)[0]) == target
assert len(patched) <= struct.unpack_from("<Q", original, 16)[0]
for delta in [-0x8000000, -4, 0, 4, 0x7fffffc]:
    assert trace.branch_target(0x8000000, trace.branch(0x8000000, 0x8000000 + delta)) == 0x8000000 + delta
try:
    trace.instrument(original[:-1] + bytes([original[-1] ^ 1]))
except AssertionError:
    pass
else:
    raise AssertionError("Unpinned kernel accepted")
print("PASS: Clang confirms all trampoline bytes; exact branch return, header preservation, image bounds and input pin checked")
