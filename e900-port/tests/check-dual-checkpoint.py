#!/usr/bin/env python3
"""Exercise the actual dual-stage boot script with persistent storage stubs."""
import argparse
import gzip
import importlib.util
import json
import pathlib
import struct
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("kit", type=pathlib.Path)
parser.add_argument("original", type=pathlib.Path)
args = parser.parse_args()
port = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dual", port / "scripts/make-dual-checkpoint.py")
dual = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dual)
meta = json.loads((args.kit / "dual-provenance.json").read_text())
original = args.original.read_bytes()
image = (args.kit / "e900-Image-mmu").read_bytes()
hook, scratch, size = meta["mmu_hook"], meta["mmu_stub"], meta["mmu_stub_bytes"]
assert len(image) == len(original) and image[:64] == original[:64]
assert image[:hook] == original[:hook] and image[hook + 4:scratch] == original[hook + 4:scratch]
assert image[scratch + size:] == original[scratch + size:]
assert hook // 4096 == scratch // 4096 == (scratch + size - 1) // 4096
assert image[scratch + size - 16:scratch + size] == struct.pack("<QII", 0x074ff000, 0xe9100001, 0)
entries = dual.cpio_read(gzip.decompress((args.kit / "e900-uInitrd-user").read_bytes()[64:]))
files = {name: body for name, _, body in entries}
assert files["init"] == (args.kit / "diagnostic-init.sh").read_bytes()
assert files["e9/userspace-proof.txt"] == (args.kit / "E9UPASS.BIN").read_bytes()
assert files["e9/user-marker.bin"] == struct.pack("<I", 0xe9100002)
assert files["init.ce-original"].startswith(b"#!/bin/sh")
subprocess.run(["sh", "-n", str(args.kit / "diagnostic-init.sh")], check=True)
harness = r'''
mode="$1"; logphase="$2"; ram="$3"; mmu="$4"; user="$5"; sourcefile="$6"
bootargs=android; calls=none; nwrite=0
setenv() { printf -v "$1" '%s' "$2"; }
fatload() {
  filesize=200
  case "$4" in
    E9LOG.TXT) logbuf="$logphase";;
    E9P1FLAG.BIN) next=P1;;
    E9P2FLAG.BIN) next=P2;;
    E9MMU.TXT) target=mmu; logbuf="$mmu";;
    E9USER.TXT) logbuf="$user";;
    E9MPASS.BIN|E9UPASS.BIN) next=yes;;
    E9D*.BIN) next="$4";;
    E9MSEED.BIN) ram=e9100000;;
    E9USEED.BIN) ram=e9100010;;
  esac
  return 0
}
cmp.b() {
  [ "$mode" != guardfail ] || return 1
  if [ "$2" = 0x04001000 ]; then [ "$logbuf" = "$next" ]; return $?; fi
  if [ "$1" = 0x04000000 ]; then [ "$logbuf" = "$readbuf" ]; else [ "$next" = "$readbuf" ]; fi
}
usb() {
  case "$1" in
    start|dev) return 0;;
    read)
      if [ "$3" = MMULBA ]; then readbuf="$mmu"; else readbuf="$logphase"; fi
      return 0;;
    write)
      [ "$mode" != iofail ] || return 1
      if [ "$3" = MMULBA ]; then mmu="$next"; else logphase="$next"; fi
      nwrite=$((nwrite+1)); return 0;;
  esac
  return 1
}
itest.l() { [ "$ram" = "${3#0x}" ]; }
setexpr() { return 1; }
booti() { calls="$calls $*"; return 1; }
. "$sourcefile" >/dev/null
printf '%s\n%s\n' "$calls" "$bootargs"
'''
# Replace only constants for the command emulator's device addressing.
harness = harness.replace("MMULBA", hex(meta["mmu_slot"]["lba"]))
for mode, phase, ram, mmu, user, expected in [
    ("ok", "old", "0", "no", "no", "0x15000000"),
    ("ok", "P1", "e9100001", "no", "no", "0x15000000"),
    ("ok", "P1", "0", "no", "no", None),
    ("ok", "P2", "e9100002", "yes", "no", None),
    ("ok", "P2", "0", "yes", "yes", None),
    ("ok", "P2", "0", "yes", "no", None),
    ("iofail", "old", "0", "no", "no", None),
    ("guardfail", "old", "0", "no", "no", None),
]:
    result = subprocess.run(["bash", "-c", harness, "dual-test", mode, phase, ram, mmu, user,
                             str(args.kit / "dual-boot.src")], capture_output=True, text=True, check=True)
    calls = result.stdout.splitlines()[0]
    assert (expected in calls) if expected else calls == "none", (mode, phase, ram, mmu, user, result.stdout)
print("PASS: MMU patch bounds, initramfs contents and real two-stage script; warm results, missing markers, no-repeat and failed writes")
