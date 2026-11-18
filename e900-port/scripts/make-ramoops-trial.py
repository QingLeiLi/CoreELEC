#!/usr/bin/env python3
"""Restore ramoops binding after retiring the RAM checkpoint probes."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

PORT=Path(__file__).resolve().parents[1]
PINNED='c1d06d03a2eac0a10f6623977100e675222732dd47a34d49c584c57f6ecbda9a'
NODE='/reserved-memory/ramoops@0x07400000'
KERNEL='2126e5a3aac587db015ec3bb879421c28ae045dccf24f12361f653bcbe3a11b8'
INITRD='73ec69b4b84df29c6423f8f76835a8a51b161bae615d1081fe857e54f7eb58e2'

def make(source,output,kernel,initrd):
    assert not output.exists()
    assert hashlib.sha256(kernel.read_bytes()).hexdigest()==KERNEL, "Requires the retired-probe normal kernel"
    assert hashlib.sha256(initrd.read_bytes()).hexdigest()==INITRD, "Requires original CE initramfs without RAM checkpoint writers"
    data=source.read_bytes();assert hashlib.sha256(data).hexdigest()==PINNED
    spec=importlib.util.spec_from_file_location('ramoops_board',PORT/'scripts/validate-board.py')
    board=importlib.util.module_from_spec(spec);spec.loader.exec_module(board)
    before=board.read_fdt(data)
    assert before[NODE]['compatible']==b'e9trace\0'
    assert board.cells(before[NODE]['reg'])==[0,0x07400000,0,0x100000]
    assert data.count(b'e9trace\0')==1
    changed=data.replace(b'e9trace\0',b'ramoops\0')
    after=board.read_fdt(changed)
    assert before.keys()==after.keys()
    differences=[]
    for node,props in before.items():
        assert props.keys()==after[node].keys()
        for key,value in props.items():
            if value!=after[node][key]:differences.append((node,key))
    assert differences==[(NODE,'compatible')]
    assert after[NODE]['compatible']==b'ramoops\0'
    output.mkdir(parents=True)
    target=output/'e900-full.dtb';target.write_bytes(changed)
    board.validate(target)
    sha=hashlib.sha256(changed).hexdigest()
    (output/'SHA256SUMS').write_text(sha+'  e900-full.dtb\n')
    (output/'ramoops-provenance.json').write_text(json.dumps({'source_sha256':PINNED,'dtb_sha256':sha,'changed_properties':differences,'retired_checkpoint_probes_required':True,'verified_kernel_sha256':KERNEL,'verified_initrd_sha256':INITRD,'hardware_tested':False,'kernel_unchanged':True},indent=2)+'\n')
    print('PASS: only reserved-memory ramoops compatible restored; all other DT properties unchanged')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--kernel',type=Path,required=True);p.add_argument('--initrd',type=Path,required=True)
    a=p.parse_args();make(a.source,a.output,a.kernel,a.initrd)
