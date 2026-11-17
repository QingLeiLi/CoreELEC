#!/usr/bin/env python3
"""Restore CE init flow, instrument progress and fix the observed FB reservation."""
import argparse
import gzip
import hashlib
import importlib.util
import json
import pathlib
import struct
import subprocess
import tempfile

PORT = pathlib.Path(__file__).resolve().parents[1]


def load(name, file):
    s = importlib.util.spec_from_file_location(name, PORT / "scripts" / file)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def make(kit, output, mkimage, dtc):
    dual = load("full_cpio", "make-dual-checkpoint.py")
    trace = load("full_trace", "make-entry-trace.py")
    usb = load("full_usb", "prepare-usb-image.py")
    legacy = load("full_legacy", "make-booti-test-kit.py")
    assert not output.exists()
    output.mkdir(parents=True)
    original_dtb = (kit / "dtb.img").read_bytes()
    assert hashlib.sha256(original_dtb).hexdigest() == trace.PINNED_DTB
    with tempfile.TemporaryDirectory(prefix="e900-full-dtb-") as temp:
        source = pathlib.Path(temp) / "board.dts"
        subprocess.run([str(dtc), "-q", "-I", "dtb", "-O", "dts", "-o", str(source), str(kit / "dtb.img")], check=True)
        text = source.read_text()
        start = text.index("\t\tlinux,meson-fb {")
        end = text.index("\n\t\t};", start)
        old = text[start:end]
        import re
        new = re.sub(r'\n\s*(size|alignment|alloc-ranges) = [^;]+;', '', old)
        new += '\n\t\t\treg = <0x0 0x3dc00000 0x0 0x2400000>;'
        text = text[:start] + new + text[end:]
        # Keep the tested trace page reserved but do not let ramoops clear markers.
        text = text.replace('compatible = "ramoops";', 'compatible = "e9trace";')
        source.write_text(text)
        subprocess.run([str(dtc), "-q", "-I", "dts", "-O", "dtb", "-o", str(output / "e900-full.dtb"), str(source)], check=True)
    old_nodes = usb.board.read_fdt(original_dtb)
    new_nodes = usb.board.read_fdt((output / "e900-full.dtb").read_bytes())
    fb = '/reserved-memory/linux,meson-fb'
    assert usb.board.cells(new_nodes[fb]['reg']) == [0, 0x3dc00000, 0, 0x2400000]
    assert 'reusable' in new_nodes[fb] and not any(k in new_nodes[fb] for k in ['size','alignment','alloc-ranges'])
    for path, props in old_nodes.items():
        for key,value in props.items():
            if path == fb and key in {'size','alignment','alloc-ranges'}: continue
            if path == '/reserved-memory/ramoops@0x07400000' and key == 'compatible': continue
            assert new_nodes[path][key] == value, (path,key)
    archive = gzip.decompress((kit / 'e900-uInitrd').read_bytes()[64:])
    assert hashlib.sha256(archive).hexdigest() == trace.PINNED_INITRD
    entries = dual.cpio_read(archive)
    old_init = next(body for name,_,body in entries if name == 'init')
    init = old_init.decode()
    hook = '''
# E900 trial: keep original CE flow, export checkpoints only after /flash exists.
e9_export() {
  echo "e900 ce25: $1" >/dev/kmsg
  if /usr/bin/busybox mountpoint -q /flash; then
    if /usr/bin/busybox mount -o remount,rw /flash; then
      echo "E900 ce25 checkpoint=$1" >/flash/E9BOOT.TXT
      /usr/bin/busybox dmesg >/flash/E9CELOG.TXT
      /usr/bin/busybox cat /proc/cmdline >/flash/E9CECMD.TXT
      /usr/bin/busybox sync
      /usr/bin/busybox mount -o remount,ro /flash
    fi
  fi
}
/usr/bin/busybox mknod /dev/mem c 1 1 2>/dev/null
/usr/bin/busybox dd if=/e9-full-entry.bin of=/dev/mem bs=1 seek=122679296 count=4 2>/dev/null
e9_export init_entered
'''
    anchor = 'UPDATE_ROOT=/storage/.update'
    assert init.count(anchor)==1
    init=init.replace(anchor,hook+'\n'+anchor,1)
    assert init.count('  $BOOT_STEP\n')==1
    init=init.replace('  $BOOT_STEP\n','  e9_export "before_$BOOT_STEP"\n  $BOOT_STEP\n  e9_export "after_$BOOT_STEP"\n',1)
    switch='exec /usr/bin/busybox switch_root /sysroot /usr/lib/systemd/systemd $INIT_ARGS $INIT_UNIT'
    assert init.count(switch)==1
    init=init.replace(switch,'e9_export before_switch_root\n/usr/bin/busybox dd if=/e9-full-switch.bin of=/dev/mem bs=1 seek=122679296 count=4 2>/dev/null\n'+switch,1)
    assert init.count('e9_export before_switch_root')==1
    result=[]
    for name,fields,body in entries:
        result.append((name,fields,init.encode() if name=='init' else body))
    inode=max(fields[0] for _,fields,_ in result)+1
    for name,value in [('e9-full-entry.bin',0xe9250001),('e9-full-switch.bin',0xe9250002)]:
        body=struct.pack('<I',value)
        result.append((name,[inode,0o100644,0,0,1,0,4,0,0,0,0,0,0],body));inode+=1
    cpio=dual.cpio_write(result)
    decoded={n:(f,b) for n,f,b in dual.cpio_read(cpio)}
    for name,fields,body in entries:
        if name != 'init': assert decoded[name] == (fields,body)
    (output/'init-with-progress.sh').write_text(init)
    with tempfile.TemporaryDirectory(prefix='e900-full-init-') as temp:
        packed=pathlib.Path(temp)/'init.gz';data=gzip.compress(cpio,mtime=0);packed.write_bytes(data)
        target=output/'e900-uInitrd-full'
        subprocess.run([str(mkimage),'-A','arm64','-O','linux','-T','ramdisk','-C','gzip','-n','E900 normal CE init with progress','-d',str(packed),str(target)],check=True)
        legacy.legacy_image(target,3,1,data)
    (output/'E9RSEED.BIN').write_bytes(struct.pack('<II',0xe9250000,0))
    (output/'full-provenance.json').write_text(json.dumps(dict(original_cpio_sha256=trace.PINNED_INITRD,
        original_init_preserved_except_progress_hooks=True,original_other_entries_preserved=True,
        fixed_framebuffer_region=['0x3dc00000','0x40000000'],files={p.name:usb.sha256(p) for p in output.iterdir() if p.is_file()},hardware_tested=False),indent=2)+'\n')
    print('Prepared normal CE boot trial:',output)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('kit',type=pathlib.Path);p.add_argument('output',type=pathlib.Path)
    p.add_argument('--mkimage',type=pathlib.Path,required=True);p.add_argument('--dtc',type=pathlib.Path,required=True)
    a=p.parse_args();make(a.kit,a.output,a.mkimage,a.dtc)
