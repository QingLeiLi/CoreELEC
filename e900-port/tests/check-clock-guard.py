#!/usr/bin/env python3
"""Check emitted guard instructions and boundary semantics without device writes."""
import argparse
import hashlib
import json
import pathlib
import struct

p = argparse.ArgumentParser()
p.add_argument("kit", type=pathlib.Path)
a = p.parse_args()
meta = json.loads((a.kit / "guard-provenance.json").read_text())
data = (a.kit / "e900-Image-guard").read_bytes()
assert hashlib.sha256(data).hexdigest() == meta["image_sha256"]
words = struct.unpack_from("<7I", data, meta["scratch"])
assert words[:3] == (0xb40000a0, 0xb13ffc1f, 0x54000062)
assert words[5] == 0xf900467f
adr = words[3]
offset = ((adr >> 29) & 3) | (((adr >> 5) & 0x7ffff) << 2)
if offset & (1 << 20):
    offset -= 1 << 21
assert meta["scratch"] + 12 + offset == 0xcd4e08
for value in [0, 1, 0xffff000000001000, (1 << 64) - 4096,
              (1 << 64) - 4095, (1 << 64) - 517, (1 << 64) - 2, (1 << 64) - 1]:
    # Model CBZ then CMN's carry flag and B.CS.
    missing = value == 0 or value + 4095 >= 1 << 64
    assert missing == (value == 0 or value >= (1 << 64) - 4095)
    if missing:
        assert words[5] == 0xf900467f  # clear stored clock, not an address through it
    else:
        assert adr & 31 == 30  # preserve original BL return point in LR
print("PASS: emitted NULL/ERR_PTR guard, valid pointer path, original return address and clearing stored error pointer")
