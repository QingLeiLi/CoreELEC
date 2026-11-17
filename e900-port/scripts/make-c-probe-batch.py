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


def make(original, slot_path, output, mkimage, late=False, bisect=False, initcalls=False, functions=False, window=None, run_id=17, counts=None, di_probe=False):
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
    stages = STAGES
    batch = "batch12"
    if late:
        batch = "batch13"
        stages = [(0x12b0834, 0x900040b3, "after_setup_arch"),
                  (0x12b0994, 0x52800000, "after_boot_parameter_processing"),
                  (0x12b0a68, 0x94005ae9, "after_interrupt_enable"),
                  (0x12b0b50, 0x97e8e137, "before_rest_init")]
        # preserve_boot_args stores x0..x3 at this mapped writable location.
        assert struct.unpack_from("<4I", data, 0x12b0024) == (0xd0002e20, 0x91000000, 0xa9000415, 0xa9010c02)
    if bisect:
        assert late
        batch = "bisect14"
        stages = [(0x12b0b6c, 0xa9bb7bfd, "kernel_init_freeable_entry"),
                  (0x12b0c54, 0x94002f9b, "before_smp_init"),
                  (0x12b0d18, 0x90ffeea0, "after_main_initcalls_before_console_open"),
                  (0xce911c, 0xf9400a60, "before_userspace_exec_attempt")]
    if initcalls:
        assert bisect and late
        batch = "bisect15"
        stages = [(0x12b0c58, 0x913ea273, "after_smp_init"),
                  (0x12b0c94, 0xb202e7e0, "before_main_initcall_levels"),
                  (0x12b0d10, 0xf10022bf, "initcall_levels_0_through_3_completed"),
                  (0x12b0d10, 0xf10022bf, "initcall_levels_0_through_5_completed")]
    records = []
    function_counts = [112,225,338,25]
    function_levels = [6,6,6,7]
    if functions:
        assert late and bisect and not initcalls
        batch = "bisect16"
        # Validate the relocated level table rather than trusting source counts.
        rel = {target-0xffffff8009080000: value-0xffffff8009080000
               for target,kind,value in (struct.unpack_from('<QQQ', data, p)
                  for p in range(0x13a9d10,0x1868128,24)) if kind==1027}
        boundaries=[rel[0x1312c18+i*8] for i in range(9)]
        assert [(boundaries[i+1]-boundaries[i])//8 for i in [6,7]]==[400,51]
        stages=[(0x12b0cf4,0xeb00033f,label) for label in
                ['device_first_112_completed','device_first_225_completed',
                 'device_first_338_completed','device_all_and_late_first_25_completed']]
    if window:
        assert functions
        low,high=map(int,window.split(':'))
        assert 0<=low<high<=400 and (high-low>=8 or counts)
        middle=(low+high)//2
        upper=(middle+high)//2
        function_counts=[(low+middle)//2,middle,upper,(upper+high)//2]
        if counts:
            function_counts=list(map(int,counts.split(',')))
            assert len(function_counts)==4 and all(low<=x<=high for x in function_counts)
            assert all(a<b for a,b in zip(function_counts,function_counts[1:]))
        function_levels=[6]*4
        assert 17<=run_id<=99
        batch=f"bisect{run_id}"
        window_magic=0xe9000001 | (int(str(run_id),16)<<16)
        stages=[(0x12b0cf4,0xeb00033f,f'device_first_{count}_completed') for count in function_counts]
    if di_probe:
        assert late and bisect and not functions and not window
        batch="bisect20"
        stages=[(0xcd4904,0xa9b97bfd,'di_probe_entry'),
                (0xcd4b40,0xf9413b00,'di_probe_after_reserved_memory_init'),
                (0xcd51a8,0x3942f2a0,'di_probe_before_di_hw_init'),
                (0xcd51bc,0xf9401e98,'di_probe_after_di_hw_init')]
    for index, (hook, expected, label) in enumerate(stages):
        assert struct.unpack_from("<I", data, hook)[0] == expected
        if late:
            with tempfile.TemporaryDirectory(prefix="e900-late-stub-") as t:
                obj = pathlib.Path(t) / "stub.o"
                extra = []
                if functions:
                    extra=[f'-DE9_FN_LEVEL={function_levels[index]}',
                           f'-DE9_FN_BYTES={function_counts[index]*8}',
                           f'-DE9_RETURN_BRANCH={hex(trace.branch(0xcf136c,0x12b0cf8))}']
                if initcalls and index >= 2:
                    extra = [f"-DE9_LEVEL_PREFIX={4 if index == 2 else 6}",
                             f"-DE9_RETURN_BRANCH={hex(trace.branch(0xcf135c, 0x12b0d14))}"]
                subprocess.run(["clang", "-target", "aarch64-none-elf", f"-DE9_LATE_MAGIC={hex((0xe9200001 if di_probe else window_magic if window else 0xe9160001 if functions else 0xe9150001 if initcalls else 0xe9140001 if bisect else 0xe9130001)+index)}", *extra, "-c", str(PORT / "boards/e900-late-reset.S"), "-o", str(obj)], check=True)
                payload = reset.text_section(obj.read_bytes())
                if functions:
                    assert struct.unpack_from('<I',payload,24)[0]==0xeb00033f
                    assert trace.branch_target(0xcf136c,struct.unpack_from('<I',payload,28)[0])==0x12b0cf8
                if initcalls and index >= 2:
                    assert struct.unpack_from("<4I", payload) == (0xf10002bf | ((4 if index==2 else 6)<<10), 0x54000060, 0xf10022bf, trace.branch(0xcf135c,0x12b0d14))
            assert len(payload) <= 128
            stub = payload.ljust(128, b"\0")
        image = bytearray(data)
        image[0xcf1350:0xcf13d0] = stub
        struct.pack_into("<I", image, hook, trace.branch(hook, 0xcf1350))
        assert image[:64] == data[:64]
        edits = sorted([(0xcf1350, 0xcf13d0), (hook, hook + 4)])
        end = 0
        for start, stop in edits:
            assert image[end:start] == data[end:start]
            end = stop
        assert image[end:] == data[end:]
        name = f"E9B{index}.IMG"
        (output / name).write_bytes(image)
        records.append(dict(index=index, hook=hook, label=label, image=name,
                            sha256=hashlib.sha256(image).hexdigest()))
        for status in ["ARM", "PASS", "FAIL"]:
            text = f"E900 {batch} stage={index} status={status}\ncheckpoint={label}\nnonce={slot['nonce']}\n".encode()
            (output / f"E9B{index}{status}.BIN").write_bytes(text.ljust(511, b" ") + b"\n")
    (output / "E9BSEED.BIN").write_bytes(struct.pack("<II", 0xe9120000, 0))
    template = (PORT / "boards/e900-usb-write-probe.src.in").read_text()
    def write(name):
        lines = template.replace("@LBA@", hex(slot["lba"])).replace("E9NEXT.BIN", name).splitlines()
        return [l for l in lines if not l.startswith("echo ") and not l.startswith("setenv bootargs ")] + [
            'if test "${e9_write}" != "passed"; then setenv e9_ok no; fi']
    out = ['echo "E900 automatic C bootstrap batch"', 'setenv e9_saved_bootargs "${bootargs}"',
           'setenv e9_cursor '+('1' if bisect else '0'), 'setenv e9_armed no', 'setenv e9_ok yes', 'usb start']
    route_pass = {0:4, 1:2, 2:3, 3:4}
    route_fail = {0:4, 1:0, 2:4, 3:4}
    # Identify the last durable state before any write. Full-sector comparison
    # avoids confusing this batch with earlier runs or a different USB drive.
    for i, _, _ in [(r['index'],r['hook'],r['label']) for r in records]:
        for status in ['ARM','PASS','FAIL']:
            out += ['if fatload usb 0:1 0x04000000 E9LOG.TXT; then',
                    f'  if fatload usb 0:1 0x04001000 E9B{i}{status}.BIN; then',
                    '    if cmp.b 0x04000000 0x04001000 0x200; then',
                    f'      setenv e9_cursor {i if status=="ARM" else (route_pass[i] if bisect else i+1) if status=="PASS" else (route_fail[i] if bisect else len(stages))}',
                    f'      setenv e9_armed {"yes" if status=="ARM" else "no"}',
                    '    fi', '  fi', 'fi']
    if bisect: out += ['for e9_round in 0 1 2 3; do']
    for i, _, _ in [(r['index'],r['hook'],r['label']) for r in records]:
        out += [f'if test "${{e9_cursor}}" = "{i}"; then',
                '  if test "${e9_armed}" = "yes"; then', '    setenv e9_stage unknown',
                '    if itest.l *0x074ff000 == 0xe9120001; then setenv e9_stage e9120001; else',
                '      if setexpr e9_stage *0x074ff000 + 0; then echo "batch marker read"; fi', '    fi',
                '    if test "${e9_stage}" = "e9120001"; then']
        out += ['      '+l for l in write(f'E9B{i}PASS.BIN')]
        out += [f'      if test "${{e9_ok}}" = "yes"; then setenv e9_cursor {route_pass[i] if bisect else i+1}; setenv e9_armed no; fi', '    else']
        out += ['      '+l for l in write(f'E9B{i}FAIL.BIN')]
        out += [f'      setenv e9_cursor {route_fail[i] if bisect else len(stages)}', '      setenv e9_armed no', '    fi', '  else']
        out += [f'    if fatload usb 0:1 0x11000000 E9B{i}.IMG; then',
                '      if fatload usb 0:1 0x15000000 e900-uInitrd; then',
                '        if fatload usb 0:1 0x18000000 e900-trace.dtb; then',
                '          if fatload usb 0:1 0x074ff000 E9BSEED.BIN; then']
        out += ['            '+l for l in write(f'E9B{i}ARM.BIN')]
        out += ['            if test "${e9_ok}" = "yes"; then',
                '              setenv bootargs "${e9_saved_bootargs} e9probe=batch12_stub"',
                '              booti 0x11000000 0x15000000 0x18000000', '            fi',
                '          fi', '        fi', '      fi', '    fi', '  fi', 'fi']
    if bisect: out += ['done']
    out += ['setenv bootargs "${e9_saved_bootargs} e9probe=batch12 e9_cursor=${e9_cursor} e9_ok=${e9_ok}"']
    source = '\n'.join(out)+'\n'
    source = source.replace('e9probe=batch12', 'e9probe='+batch)
    if bisect:
        source = source.replace('              booti 0x11000000 0x15000000 0x18000000',
                                '              booti 0x11000000 0x15000000 0x18000000\n              setenv e9_cursor 4\n              setenv e9_ok no')
    if late:
        # Two DRAM-base conventions supported by these old bootloaders. Each
        # stage has its own magic; an earlier result cannot satisfy the next.
        for i in range(len(stages)):
            old = '    if itest.l *0x074ff000 == 0xe9120001; then setenv e9_stage e9120001; else\n      if setexpr e9_stage *0x074ff000 + 0; then echo "batch marker read"; fi\n    fi'
            magic = hex((0xe9200001 if di_probe else window_magic if window else 0xe9160001 if functions else 0xe9150001 if initcalls else 0xe9140001 if bisect else 0xe9130001)+i)
            new = f'    if itest.l *0x028f6018 == {magic}; then setenv e9_stage e9120001; else\n      if itest.l *0x029f6018 == {magic}; then setenv e9_stage e9120001; fi\n    fi'
            assert old in source
            source = source.replace(old,new,1)
    assert len(source)<65536
    (output/'batch.src').write_text(source)
    script=output/'s905_autoscript'
    subprocess.run([str(mkimage),'-A','arm','-O','linux','-T','script','-C','none','-n','E900 automatic bootstrap batch','-d',str(output/'batch.src'),str(script)],check=True)
    usb.check_script(script,source.encode())
    for name in ['aml_autoscript','cfgload']:shutil.copy2(script,output/name)
    (output/'batch-provenance.json').write_text(json.dumps(dict(slot=slot,stages=records,batch=batch,function_counts=function_counts,function_levels=function_levels,window=window,script_sha256=usb.sha256(script),hardware_tested=False),indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('original',type=pathlib.Path);p.add_argument('slot',type=pathlib.Path);p.add_argument('output',type=pathlib.Path)
    p.add_argument('--mkimage',required=True,type=pathlib.Path);p.add_argument('--late',action='store_true');p.add_argument('--bisect',action='store_true');p.add_argument('--initcalls',action='store_true');p.add_argument('--functions',action='store_true');p.add_argument('--window');p.add_argument('--run-id',type=int,default=17);p.add_argument('--counts');p.add_argument('--di-probe',action='store_true');a=p.parse_args()
    make(a.original,a.slot,a.output,a.mkimage,a.late,a.bisect,a.initcalls,a.functions,a.window,a.run_id,a.counts,a.di_probe)
