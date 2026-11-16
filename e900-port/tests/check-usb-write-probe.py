#!/usr/bin/env python3
"""Check FAT slot bounds and fail-closed writes using the actual probe source."""
import importlib.util
import pathlib
import struct
import subprocess
import tempfile

PORT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("write_probe", PORT / "scripts/prepare-usb-write-probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
mbr, bpb, fat, root = [bytearray(512) for _ in range(4)]
mbr[510:] = bpb[510:] = b"\x55\xaa"
struct.pack_into("<II", mbr, 454, 2048, 5000)
struct.pack_into("<H", bpb, 11, 512)
bpb[13] = 1
struct.pack_into("<H", bpb, 14, 1)
bpb[16] = 2
struct.pack_into("<H", bpb, 17, 16)
struct.pack_into("<H", bpb, 19, 5000)
struct.pack_into("<H", bpb, 22, 20)
struct.pack_into("<H", fat, 10, 0xffff)
root[:11] = b"E9LOG   TXT"
root[11] = 0x20
struct.pack_into("<H", root, 26, 5)
struct.pack_into("<I", root, 28, 512)
payload = b"unique evidence fixture".ljust(512, b" ")
sectors = {0: mbr, 2048: bpb, 2049: fat, 2089: root, 2093: payload}


def read(lba, count):
    return b"".join(bytes(sectors.get(i, bytes(512))) for i in range(lba, lba + count))


disk = probe.FatDisk(read)
assert disk.evidence_slot(payload)["lba"] == 2093
for mutate, restore in [
    (lambda: struct.pack_into("<I", root, 28, 513), lambda: struct.pack_into("<I", root, 28, 512)),
    (lambda: struct.pack_into("<H", root, 26, 0), lambda: struct.pack_into("<H", root, 26, 5)),
    (lambda: struct.pack_into("<H", fat, 10, 6), lambda: struct.pack_into("<H", fat, 10, 0xffff)),
    (lambda: sectors.update({2093: b"x" * 512}), lambda: sectors.update({2093: payload})),
]:
    mutate()
    try:
        disk.evidence_slot(payload)
    except AssertionError:
        pass
    else:
        raise AssertionError("Unsafe or mismatched file slot accepted")
    restore()

source = (PORT / "boards/e900-usb-write-probe.src.in").read_text().replace("@LBA@", "0x82d")
harness = r'''
scenario="$1"; sourcefile="$2"; writes=0; comparisons=0; current=before; bootargs=android
setenv() { printf -v "$1" '%s' "$2"; }
usb() {
  case "$1" in
    start|dev) return 0;;
    read) [ "$scenario" != readfail ] || return 1; readbuf="$current"; return 0;;
    write)
      [ "$scenario" != unsupported ] || return 1
      [ "$2" = 0x04001000 ] && [ "$3" = 0x82d ] && [ "$4" = 1 ] || return 1
      writes=$((writes+1)); current=after; return 0;;
  esac
  return 1
}
fatload() { filesize=200; return 0; }
cmp.b() {
  comparisons=$((comparisons+1))
  [ "$scenario" != badguard ] || return 1
  [ "$scenario" != nocmp ] || return 1
  if [ "$1" = 0x04000000 ]; then [ "$readbuf" = before ]; else [ "$readbuf" = after ]; fi
}
. "$sourcefile" >/dev/null
printf '%s %s\n' "$writes" "$e9_write"
'''
with tempfile.TemporaryDirectory(prefix="e900-write-guard-") as temporary:
    path = pathlib.Path(temporary) / "probe.src"
    path.write_text(source)
    for scenario, expected in [("ok", "1 passed"), ("badguard", "0 guard_unconfirmed"),
                               ("nocmp", "0 guard_unconfirmed"), ("readfail", "0 guard_unconfirmed"),
                               ("unsupported", "0 command_failed")]:
        result = subprocess.run(["bash", "-c", harness, "write-test", scenario, str(path)],
                                capture_output=True, text=True, check=True)
        assert result.stdout.strip() == expected, result.stdout
print("PASS: FAT file bounds, cluster/length/content rejection, and actual script write guards")
