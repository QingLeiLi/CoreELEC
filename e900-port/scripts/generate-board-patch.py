#!/usr/bin/env python3
"""Generate the board addition against the verified pinned DTS Makefile."""
import difflib
import hashlib
import json
import os
import pathlib

port = pathlib.Path(__file__).resolve().parents[1]
audit = pathlib.Path(os.environ.get("E900_AUDIT_ROOT", port.parent / "coreelec-audit"))
makefile = "arch/arm64/boot/dts/amlogic/Makefile"
base = (audit / "sources" / makefile.replace("/", "__")).read_bytes()
expected = next(row for row in json.loads((port / "tests/source-fixtures.json").read_text()) if row["path"] == makefile)
assert hashlib.sha256(base).hexdigest() == expected["sha256"]
old = base.decode()
anchor = "dtb-$(CONFIG_ARM64) += coreelec-gxl/gxl_p212_1g.dtb\n"
assert old.count(anchor) == 1
name = "gxlx2_p291_1g_e900v21c"
new = old.replace(anchor, anchor + f"dtb-$(CONFIG_ARM64) += coreelec-gxl/{name}.dtb\n")
destination = f"arch/arm64/boot/dts/amlogic/coreelec-gxl/{name}.dts"
parts = ["Subject: [EXPERIMENTAL] add E900V21C GXLX2 1GB USB board\n\n",
         "Hardware validation is pending; internal MMC controllers are disabled.\n\n",
         f"diff --git a/{makefile} b/{makefile}\n"]
parts.extend(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                fromfile="a/" + makefile, tofile="b/" + makefile))
parts.extend([f"diff --git a/{destination} b/{destination}\n", "new file mode 100644\n"])
parts.extend(difflib.unified_diff([], (port / "boards" / (name + ".dts")).read_text().splitlines(True),
                                fromfile="/dev/null", tofile="b/" + destination))
output = port / "patches/linux/0003-e900v21c-usb-board.patch"
output.write_text("".join(parts))
print(output)
