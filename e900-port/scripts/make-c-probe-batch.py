#!/usr/bin/env python3
"""Build three automatic C bootstrap reset probes using one persistent ledger."""
import argparse
import hashlib
import importlib.util
import json
import pathlib
import shutil
import struct
import subprocess
import tempfile

PORT = pathlib.Path(__file__).resolve().parents[1]
STAGES = [(0x12b07c8, 0xa9bb7bfd, "C_entry"),
          (0x12b0818, 0x90ffd281, "before_kernel_banner"),
          (0x12b082c, 0x910123e0, "before_setup_arch")]


def make(original, slot_path, output, mkimage):
    def load(name, filename):
        s = importlib.util.spec_from_file_location(name, PORT / "scripts" / filename)
        m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
        return m
    trace = load("batch_trace", "make-entry-trace.py")
    reset = load("batch_reset", "make-reset-entry-image.py")
    usb = load("batch_usb", "prepare-usb-image.py")
    slot = json.loads(slot_path.read_text())
    assert slot["hardware_write_tested"] is True
    data = original.read_bytes()
    assert hashlib.sha256(data).hexdigest() == trace.PINNED_IMAGE
    assert not output.exists()
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="e900-batch-stub-") as t:
        obj = pathlib.Path(t) / "stub.o"
        subprocess.run(["clang", "-target", "aarch64-none-elf", "-c", str(PORT / "boards/e900-c-entry-reset.S"), "-o", str(obj)], check=True)
        stub = reset.text_section(obj.read_bytes())
    assert len(stub) == 128
    records = []
    for index, (hook, expected, label) in enumerate(STAGES):
        assert struct.unpack_from("<I", data, hook)[0] == expected
        image = bytearray(data)
        image[0xcf1350:0xcf13d0] = stub
        struct.pack_into("<I", image, hook, trace.branch(hook, 0xcf1350))
        assert image[:64] == data[:64]
        assert image[:0xcf1350] == data[:0xcf1350]
        assert image[0xcf13d0:hook] == data[0xcf13d0:hook]
        assert image[hook + 4:] == data[hook + 4:]
        name = f"E9B{index}.IMG"
        (output / name).write_bytes(image)
        records.append(dict(index=index, hook=hook, label=label, image=name,
                            sha256=hashlib.sha256(image).hexdigest()))
        for status in ["ARM", "PASS", "FAIL"]:
            text = f"E900 batch12 stage={index} status={status}\ncheckpoint={label}\nnonce={slot['nonce']}\n".encode()
            (output / f"E9B{index}{status}.BIN").write_bytes(text.ljust(511, b" ") + b"\n")
    (output / "E9BSEED.BIN").write_bytes(struct.pack("<II", 0xe9120000, 0))
    template = (PORT / "boards/e900-usb-write-probe.src.in").read_text()
    def write(name):
        lines = template.replace("@LBA@", hex(slot["lba"])).replace("E9NEXT.BIN", name).splitlines()
        return [l for l in lines if not l.startswith("echo ") and not l.startswith("setenv bootargs ")] + [
            'if test "${e9_write}" != "passed"; then setenv e9_ok no; fi']
    out = ['echo "E900 automatic C bootstrap batch"', 'setenv e9_saved_bootargs "${bootargs}"',
           'setenv e9_cursor 0', 'setenv e9_armed no', 'setenv e9_ok yes', 'usb start']
    # Identify the last durable state before any write. Full-sector comparison
    # avoids confusing this batch with earlier runs or a different USB drive.
    for i, _, _ in [(r['index'],r['hook'],r['label']) for r in records]:
        for status in ['ARM','PASS','FAIL']:
            out += ['if fatload usb 0:1 0x04000000 E9LOG.TXT; then',
                    f'  if fatload usb 0:1 0x04001000 E9B{i}{status}.BIN; then',
                    '    if cmp.b 0x04000000 0x04001000 0x200; then',
                    f'      setenv e9_cursor {i if status=="ARM" else i+1 if status=="PASS" else 3}',
                    f'      setenv e9_armed {"yes" if status=="ARM" else "no"}',
                    '    fi', '  fi', 'fi']
    for i, _, _ in [(r['index'],r['hook'],r['label']) for r in records]:
        out += [f'if test "${{e9_cursor}}" = "{i}"; then',
                '  if test "${e9_armed}" = "yes"; then', '    setenv e9_stage unknown',
                '    if itest.l *0x074ff000 == 0xe9120001; then setenv e9_stage e9120001; else',
                '      if setexpr e9_stage *0x074ff000 + 0; then echo "batch marker read"; fi', '    fi',
                '    if test "${e9_stage}" = "e9120001"; then']
        out += ['      '+l for l in write(f'E9B{i}PASS.BIN')]
        out += [f'      if test "${{e9_ok}}" = "yes"; then setenv e9_cursor {i+1}; setenv e9_armed no; fi', '    else']
        out += ['      '+l for l in write(f'E9B{i}FAIL.BIN')]
        out += ['      setenv e9_cursor 3', '    fi', '  else']
        out += [f'    if fatload usb 0:1 0x11000000 E9B{i}.IMG; then',
                '      if fatload usb 0:1 0x15000000 e900-uInitrd; then',
                '        if fatload usb 0:1 0x18000000 e900-trace.dtb; then',
                '          if fatload usb 0:1 0x074ff000 E9BSEED.BIN; then']
        out += ['            '+l for l in write(f'E9B{i}ARM.BIN')]
        out += ['            if test "${e9_ok}" = "yes"; then',
                '              setenv bootargs "${e9_saved_bootargs} e9probe=batch12_stub"',
                '              booti 0x11000000 0x15000000 0x18000000', '            fi',
                '          fi', '        fi', '      fi', '    fi', '  fi', 'fi']
    out += ['setenv bootargs "${e9_saved_bootargs} e9probe=batch12 e9_cursor=${e9_cursor} e9_ok=${e9_ok}"']
    source = '\n'.join(out)+'\n'
    assert len(source)<65536
    (output/'batch.src').write_text(source)
    script=output/'s905_autoscript'
    subprocess.run([str(mkimage),'-A','arm','-O','linux','-T','script','-C','none','-n','E900 automatic bootstrap batch','-d',str(output/'batch.src'),str(script)],check=True)
    usb.check_script(script,source.encode())
    for name in ['aml_autoscript','cfgload']:shutil.copy2(script,output/name)
    (output/'batch-provenance.json').write_text(json.dumps(dict(slot=slot,stages=records,script_sha256=usb.sha256(script),hardware_tested=False),indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('original',type=pathlib.Path);p.add_argument('slot',type=pathlib.Path);p.add_argument('output',type=pathlib.Path)
    p.add_argument('--mkimage',required=True,type=pathlib.Path);a=p.parse_args()
    make(a.original,a.slot,a.output,a.mkimage)
