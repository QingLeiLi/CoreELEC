#!/usr/bin/env python3
"""Add a bounded early kernel capture service to a verified normal-init trial."""
import argparse
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile

PORT = Path(__file__).resolve().parents[1]

def make(source, output, mkimage):
    assert not output.exists()
    spec = importlib.util.spec_from_file_location('capture_cpio', PORT/'scripts/make-dual-checkpoint.py')
    cpio = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cpio)
    blob = source.read_bytes()
    assert blob[:4] == bytes.fromhex('27051956')
    entries = cpio.cpio_read(gzip.decompress(blob[64:]))
    init = next(b for n,_,b in entries if n == 'init').decode()
    anchor = 'e9_export before_kernel_overlays\n'
    assert init.count(anchor) == 1
    hook = '''# Install only into this boot's runtime systemd configuration.
/usr/bin/busybox mkdir -p /sysroot/run/systemd/system/sysinit.target.d
/usr/bin/busybox cp /e9-capture.service /sysroot/run/systemd/system/e900-kernel-capture.service
/usr/bin/busybox cp /e9-capture.sh /sysroot/run/e900-kernel-capture.sh
/usr/bin/busybox cp /e9-capture-target.conf /sysroot/run/systemd/system/sysinit.target.d/e900-capture.conf
'''
    init = init.replace(anchor, hook+anchor, 1)
    result = [(n,f,init.encode() if n == 'init' else b) for n,f,b in entries]
    inode = max(f[0] for _,f,_ in entries)+1
    for name,file in [('e9-capture.service','e900-kernel-capture.service'),('e9-capture.sh','e900-kernel-capture.sh'),('e9-capture-target.conf','e900-kernel-capture-target.conf')]:
        body = (PORT/'boards'/file).read_bytes()
        result.append((name,[inode,0o100644,0,0,1,0,len(body),0,0,0,0,0,0],body))
        inode += 1
    packed = cpio.cpio_write(result)
    decoded = {n:(f,b) for n,f,b in cpio.cpio_read(packed)}
    for n,f,b in entries:
        if n != 'init': assert decoded[n] == (f,b)
    assert init.count('exec /usr/bin/busybox switch_root /sysroot /usr/lib/systemd/systemd $INIT_ARGS $INIT_UNIT') == 1
    output.mkdir(parents=True)
    (output/'init-with-capture.sh').write_text(init)
    data = gzip.compress(packed,mtime=0)
    with tempfile.TemporaryDirectory(prefix='e900-capture-') as tmp:
        p = Path(tmp)/'init.gz'
        p.write_bytes(data)
        subprocess.run([str(mkimage),'-A','arm64','-O','linux','-T','ramdisk','-C','gzip','-n','E900 early GPU Oops capture','-d',str(p),str(output/'e900-uInitrd-full')],check=True)
    (output/'capture-provenance.json').write_text(json.dumps({'source_sha256':hashlib.sha256(blob).hexdigest(),'original_other_entries_preserved':True,'capture_max_samples':90,'capture_directory':'/storage/e900-kernel32','runtime_service_only':True,'hardware_tested':False},indent=2)+'\n')

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path)
    p.add_argument('output',type=Path)
    p.add_argument('--mkimage',type=Path,required=True)
    a = p.parse_args()
    make(a.source,a.output,a.mkimage)
