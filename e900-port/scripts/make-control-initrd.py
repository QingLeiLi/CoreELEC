#!/usr/bin/env python3
"""Version a proven diagnostic PID1's outputs without changing its boot flow."""
import argparse
import gzip
import hashlib
import importlib.util
import json
import pathlib
import struct
import subprocess
import tempfile

PORT=pathlib.Path(__file__).resolve().parents[1]


def load(name,file):
    s=importlib.util.spec_from_file_location(name,PORT/'scripts'/file)
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def make(reference,output,mkimage,run_id=27):
    assert run_id in {27,28}
    dual=load('control_cpio','make-dual-checkpoint.py')
    legacy=load('control_legacy','make-booti-test-kit.py')
    original=reference.read_bytes()
    assert hashlib.sha256(original).hexdigest()=='9226f42c7b49175017b93c21cf33d4cf83642af95cc1ce400cdcbf5b6387f53b'
    compressed=original[64:]
    legacy.legacy_image(reference,3,1,compressed)
    entries=dual.cpio_read(gzip.decompress(compressed))
    before={n:(f,b) for n,f,b in entries}
    assert before['e9/user-marker.bin'][1]==struct.pack('<I',0xe9100002)
    init=before['init'][1].decode()
    assert 'e900 dual10: diagnostic /init entered' in init
    init=init.replace('e900 dual10: diagnostic /init entered','e900 control27: diagnostic /init entered')
    init=init.replace('E9USER.TXT','E9C27.TXT').replace('E9DMESG.TXT','E9D27.TXT').replace('E9CMD.TXT','E9A27.TXT')
    proof=before['e9/userspace-proof.txt'][1]
    assert len(proof)==512 and proof.startswith(b'E900 dual10 /init reached nonce=')
    line=proof.split(b'\n',1)[0].replace(b'dual10',b'control27')+b'\n'
    proof=line.ljust(511,b' ')+b'\n'
    if run_id==28:
        init=init.replace('control27','control28').replace('E9C27','E9C28').replace('E9D27','E9D28').replace('E9A27','E9A28')
        proof=proof.replace(b'control27',b'control28')
    marker=0xe9270001 if run_id==27 else 0xe9280001
    replacements={'init':init.encode(),'e9/userspace-proof.txt':proof,'e9/user-marker.bin':struct.pack('<I',marker)}
    changed=[(n,f,replacements.get(n,b)) for n,f,b in entries]
    archive=dual.cpio_write(changed)
    after={n:(f,b) for n,f,b in dual.cpio_read(archive)}
    assert set(after)==set(before)
    for n,value in before.items():
        if n not in replacements:assert after[n]==value
    assert not output.exists();output.mkdir(parents=True)
    (output/f'control{run_id}-init.sh').write_text(init)
    (output/f'E9C{run_id}-expected.txt').write_bytes(proof)
    with tempfile.TemporaryDirectory(prefix='e900-control-init-') as t:
        packed=pathlib.Path(t)/'init.gz';payload=gzip.compress(archive,mtime=0);packed.write_bytes(payload)
        target=output/f'e900-uInitrd-control{run_id}'
        subprocess.run([str(mkimage),'-A','arm64','-O','linux','-T','ramdisk','-C','gzip','-n',f'E900 control{run_id} diagnostic PID1','-d',str(packed),str(target)],check=True)
        legacy.legacy_image(target,3,1,payload)
    (output/'E9RSEED.BIN').write_bytes(struct.pack('<II',marker-1,0))
    (output/'control-provenance.json').write_text(json.dumps(dict(reference_sha256=hashlib.sha256(original).hexdigest(),
        changed_entries=list(replacements),unchanged_entry_metadata_except_sizes=True,output_files=[f'E9C{run_id}.TXT',f'E9D{run_id}.TXT',f'E9A{run_id}.TXT'],hardware_tested=False),indent=2)+'\n')
    print('Prepared isolated bootargs control:',output)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('reference',type=pathlib.Path);p.add_argument('output',type=pathlib.Path)
    p.add_argument('--mkimage',type=pathlib.Path,required=True);p.add_argument('--run-id',type=int,default=27);a=p.parse_args();make(a.reference,a.output,a.mkimage,a.run_id)
