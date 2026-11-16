#!/usr/bin/env python3
"""Run the generated checkpoint script with simulated U-Boot storage commands."""
import argparse
import json
import pathlib
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("kit", type=pathlib.Path)
args = parser.parse_args()
report = json.loads((args.kit / "ledger-provenance.json").read_text())
labels = {stage["file"]: stage["label"] for stage in report["stages"]}
harness = r'''
mode="$1"; ram="$2"; sourcefile="$3"; calls=0; writes=0; ledger=original; bootargs=android
setenv() { printf -v "$1" '%s' "$2"; }
setexpr() {
  [ "$mode" = binary ] || return 1
  printf -v "$1" '%s' "$ram"
}
itest.l() {
  [ "$mode" != none ] || return 1
  [ "$ram" = "${3#0x}" ]
}
fatload() {
  if [ "$mode" = loadfail ] && [ "$4" = e900-Image-trace ]; then return 1; fi
  filesize=200
  case "$4" in
    E9LOG.TXT) logfilebuf="$ledger";;
    E9S*.BIN) nextpayload="$4";;
    E9ARM.BIN) ram=e9000000;;
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
  [ "$mode" != guardfail ] || return 1
  if [ "$1" = 0x04000000 ]; then [ "$logfilebuf" = "$readbuf" ]; else [ "$nextpayload" = "$readbuf" ]; fi
}
booti() { calls=$((calls+1)); return 1; }
. "$sourcefile" >/dev/null
printf '%s\n%s\n%s\n%s\n' "$calls" "$ledger" "$bootargs" "$writes"
'''
for mode, ram, count, last in [
    ("itest", "0", "1", "booti_returned_without_successful_handoff"),
    ("binary", "0", "1", "booti_returned_without_successful_handoff"),
    ("none", "0", "0", "failure_memory_readback_unconfirmed"),
    ("itest", "e9000001", "0", "ARM64_entry_marker_observed_after_reset"),
    ("itest", "e9000000", "0", "armed_RAM_marker_observed_without_entry_write"),
    ("loadfail", "0", "0", "failure_image_load_failed"),
    ("iofail", "0", "0", None),
    ("guardfail", "0", "0", None),
]:
    output = subprocess.run(["bash", "-c", harness, "ledger-test", mode, ram, str(args.kit / "ledger.src")],
                            check=True, capture_output=True, text=True).stdout.splitlines()
    assert output[0] == count, output
    if last:
        assert labels[output[1]] == last, output
        assert "e9_log=passed" in output[2], output
    else:
        assert output[1] == "original" and output[3] == "0" and "e9_log=failed" in output[2], output
        assert "e9_booti=returned" not in output[2], output
print("PASS: actual generated ledger source covers both RAM readers, missing reader, warm markers, load errors, failed writes and guards")
