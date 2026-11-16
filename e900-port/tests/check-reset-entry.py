#!/usr/bin/env python3
"""Validate the reset-only Image and the persistent no-repeat boot guard."""
import argparse
import hashlib
import json
import pathlib
import struct
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("image_kit", type=pathlib.Path)
parser.add_argument("ledger_kit", type=pathlib.Path)
parser.add_argument("original_image", type=pathlib.Path)
args = parser.parse_args()
original = args.original_image.read_bytes()
image = (args.image_kit / "e900-Image-reset").read_bytes()
meta = json.loads((args.image_kit / "reset-image-provenance.json").read_text())
assert hashlib.sha256(image).hexdigest() == meta["image_sha256"]
assert image[4:len(original)] == original[4:]
assert len(image) == len(original) + 64 <= struct.unpack_from("<Q", original, 16)[0]
assert struct.unpack_from("<I", image)[0] == 0x14000000 | (len(original) // 4)
stub = image[-64:]
assert struct.unpack_from("<4I", stub, 16) == (0x52800120, 0x72b08000, 0xd2800001, 0xd2800002)
assert struct.unpack_from("<I", stub, 32)[0] == 0xd2800003
assert stub[36:40] == struct.pack("<I", 0xd4000003)
assert struct.unpack_from("<QII", stub, 48) == (0x074ff000, 0xe9080001, 0)
report = json.loads((args.ledger_kit / "ledger-provenance.json").read_text())
labels = {stage["file"]: stage["label"] for stage in report["stages"]}
prefixes = {(args.ledger_kit / name).read_bytes()[:64] for name in labels}
assert len(prefixes) == 1
source = (args.ledger_kit / "ledger.src").read_text()
assert source.index('if cmp.b 0x04000000 0x04001000 0x40') < source.index('usb write')
harness = r'''
mode="$1"; ram="$2"; ledger="$3"; sourcefile="$4"; calls=0; writes=0; bootargs=android
setenv() { printf -v "$1" '%s' "$2"; }
setexpr() { return 1; }
itest.l() {
  [ "$mode" != none ] || return 1
  [ "$ram" = "${3#0x}" ]
}
fatload() {
  [ "$mode:$4" != loadfail:e900-Image-reset ] || return 1
  filesize=200
  case "$4" in
    E9LOG.TXT) logfilebuf="$ledger";;
    E9RSEED.BIN) ram=e9080000;;
    E9R*.BIN) nextpayload="$4";;
  esac
  return 0
}
usb() {
  case "$1" in
    start|dev) return 0;;
    read) readbuf="$ledger"; return 0;;
    write)
      [ "$mode" != iofail ] || return 1
      [ "$2" = 0x04001000 ] && [ "$4" = 1 ] || return 1
      ledger="$nextpayload"; writes=$((writes+1)); return 0;;
  esac
  return 1
}
cmp.b() {
  if [ "$3" = 0x40 ]; then [ "$logfilebuf" != original ]; return $?; fi
  if [ "$1" = 0x04000000 ]; then [ "$logfilebuf" = "$readbuf" ]; else [ "$nextpayload" = "$readbuf" ]; fi
}
booti() { calls=$((calls+1)); return 1; }
. "$sourcefile" >/dev/null
printf '%s\n%s\n%s\n' "$calls" "$ledger" "$bootargs"
'''
for mode, ram, previous, count, last in [
    ("itest", "0", "original", "1", "booti_returned_without_successful_handoff"),
    ("itest", "e9080001", "attempted", "0", "ARM64_entry_marker_observed_after_reset"),
    ("itest", "0", "attempted", "0", "failure_attempt_not_repeated_entry_unconfirmed"),
    ("none", "0", "original", "0", "failure_memory_readback_unconfirmed"),
    ("loadfail", "0", "original", "0", "failure_image_load_failed"),
    ("iofail", "0", "original", "0", None),
]:
    result = subprocess.run(["bash", "-c", harness, "reset-test", mode, ram, previous,
                             str(args.ledger_kit / "ledger.src")], check=True, capture_output=True, text=True).stdout.splitlines()
    assert result[0] == count, result
    if last:
        assert labels[result[1]] == last, result
    else:
        assert result[1] == "original" and "e9_log=failed" in result[2], result
print("PASS: same Image header/relocation, 64-byte reset-only code, SMC args, persistent no-repeat guard, warm entry markers and failures")
