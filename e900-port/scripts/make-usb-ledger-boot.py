#!/usr/bin/env python3
"""Add persistent, guarded USB checkpoints around the entry-trace boot script."""
import argparse
import hashlib
import importlib.util
import json
import pathlib
import shutil
import subprocess

PORT = pathlib.Path(__file__).resolve().parents[1]


def make(slot_path, destination, mkimage, mode="entry"):
    slot = json.loads(slot_path.read_text())
    assert slot["hardware_write_tested"] is True
    assert slot["file"] == "E9LOG.TXT" and slot["file_bytes"] == 512 and slot["write_sectors"] == 1
    assert 0 < slot["partition_start"] <= slot["lba"] < slot["partition_start"] + slot["partition_sectors"]
    assert not destination.exists()
    destination.mkdir(parents=True)
    template = (PORT / "boards/e900-usb-write-probe.src.in").read_text()
    script_source = PORT / "boards" / ("e900-usb-entry-trace.src" if mode == "entry" else "e900-usb-entry-reset.src")
    source = script_source.read_text().replace("e9probe=entry05", "e9probe=ledger07")
    stages = []

    def checkpoint(label, indent=""):
        index = len(stages)
        filename = f"E9{'S' if mode == 'entry' else 'R'}{index:03d}.BIN"
        text = f"E900 persistent checkpoint {index:03d}: {label}\nnonce={slot['nonce']}\n"
        text += "A before-command checkpoint does not prove that command completed.\n"
        payload = text.encode()
        if mode == "reset":
            prefix = ("E900 reset08 attempted nonce=" + slot["nonce"] + "\n").encode()
            assert len(prefix) <= 64
            payload = prefix.ljust(64, b" ") + payload
        assert len(payload) < 512
        payload = payload + b" " * (511 - len(payload)) + b"\n"
        (destination / filename).write_bytes(payload)
        stages.append(dict(index=index, file=filename, label=label, sha256=hashlib.sha256(payload).hexdigest()))
        lines = template.replace("@LBA@", hex(slot["lba"])).replace("E9NEXT.BIN", filename).splitlines()
        lines = [line for line in lines if not line.startswith("echo ") and not line.startswith("setenv bootargs ")]
        lines += ['if test "${e9_write}" = "passed"; then', '  setenv e9_log passed',
                  'else', '  setenv e9_log failed', 'fi']
        return [indent + 'if test "${e9_log}" = "passed"; then'] + [indent + '  ' + line for line in lines] + [indent + 'fi']

    output = ['echo "E900 persistent USB boot ledger"', 'setenv e9_log passed', 'setenv e9_booti_attempted no']
    if mode == "entry":
        output += checkpoint("script_started")
    guard_done = mode == "entry"
    for line in source.splitlines():
        stripped = line.strip()
        indent = line[:len(line) - len(line.lstrip())]
        label = None
        if stripped == "@START_CHECKPOINT@":
            guard_done = True
            output += checkpoint("reset_guard_checked", indent)
            continue
        if not guard_done:
            output.append(line)
            continue
        if stripped.startswith("if setexpr "):
            label = "before_binary_setexpr_RAM_read"
        elif stripped.startswith("if itest.l "):
            label = "before_itest_RAM_compare_" + stripped.split()[-2].rstrip(";")
        elif stripped.startswith("if fatload "):
            label = "before_load_" + stripped.split()[-2].rstrip(";")
        elif "e9_entry=reached" in stripped:
            label = "ARM64_entry_marker_observed_after_reset"
        elif "e9_entry=not_observed" in stripped:
            label = "armed_RAM_marker_observed_without_entry_write"
        elif "e9_trace=" in stripped:
            label = "failure_" + stripped.split("e9_trace=", 1)[1].rstrip('"')
        if label:
            output += checkpoint(label, indent)
        if stripped.startswith("booti "):
            output += checkpoint("before_booti", indent)
            output += [indent + 'if test "${e9_log}" = "passed"; then', indent + '  setenv e9_booti_attempted yes', indent + "  " + stripped,
                       indent + "fi"]
            output += checkpoint("booti_returned_without_successful_handoff", indent)
        elif "e9_booti=returned" in stripped:
            output += [indent + 'if test "${e9_booti_attempted}" = "yes"; then', indent + "  " + stripped,
                       indent + 'else', indent + '  setenv bootargs "${e9_saved_bootargs} e9probe=' + ('ledger07' if mode == 'entry' else 'reset08') + ' e9_booti=not_attempted"',
                       indent + 'fi']
        else:
            output.append(line)
    output += ['setenv bootargs "${bootargs} e9_log=${e9_log}"']
    script_text = "\n".join(output) + "\n"
    if mode == "reset":
        armed = [stage for stage in stages if stage["label"] == "before_booti"]
        assert len(armed) == 1
        script_text = script_text.replace("@ATTEMPTED_FILE@", armed[0]["file"])
    assert "@" not in script_text
    assert len(script_text.encode()) < 65536
    assert all(word not in script_text for word in ["saveenv", "defenv", "mmc write", "store write"])
    (destination / "ledger.src").write_text(script_text)
    script = destination / "s905_autoscript"
    subprocess.run([str(mkimage), "-A", "arm", "-O", "linux", "-T", "script", "-C", "none",
                    "-n", "E900 persistent USB boot ledger", "-d", str(destination / "ledger.src"), str(script)], check=True)
    spec = importlib.util.spec_from_file_location("usb_ledger_format", PORT / "scripts/prepare-usb-image.py")
    usb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(usb)
    usb.check_script(script, script_text.encode())
    for name in ["aml_autoscript", "cfgload"]:
        shutil.copy2(script, destination / name)
    report = dict(slot=slot, stages=stages, mode=mode, script_sha256=usb.sha256(script),
                  entry_source_sha256=usb.sha256(script_source), hardware_tested=False,
                  caveat="Last persisted checkpoint bounds progress, not necessarily the failure instruction. "
                         "ARM64 entry is only proven by an observed retained RAM entry marker.")
    (destination / "ledger-provenance.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Prepared", len(stages), "checkpoint payloads; scripts NOT deployed:", destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slot", type=pathlib.Path)
    parser.add_argument("destination", type=pathlib.Path)
    parser.add_argument("--mkimage", required=True, type=pathlib.Path)
    parser.add_argument("--mode", choices=["entry", "reset"], default="entry")
    args = parser.parse_args()
    make(args.slot.resolve(), args.destination.resolve(), args.mkimage.resolve(), args.mode)
