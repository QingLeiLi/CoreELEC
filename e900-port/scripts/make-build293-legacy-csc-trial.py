#!/usr/bin/env python3
"""Pinned Build293 SDR diagnostic: five source-mapped CSC branch decisions.

Not a portable firmware fix or all-HDR conversion. Never modifies a live kernel.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

PIN='8c87b17cead380b6cb23d1a334ec8d5372a3c8d1824d6a259666d2200f01fac8'
# offset, original instruction, new target(None = original fall-through), purpose
CHANGES=(
 (0x9ca1a4,0x54003269,0x9ca7f0,'vpp_matrix_update: run legacy hdr_support_process'),
 (0x9ca2e0,0x54002249,0x9ca728,'vpp_matrix_update: use legacy source/policy branch'),
 (0x9ca3bc,0x54002229,0x9ca800,'vpp_matrix_update: use legacy HDMI metadata callback'),
 (0x9ca420,0x54003a08,None,'vpp_matrix_update: use inlined video_process instead of video_post_process'),
 (0x9c8d40,0x5400084d,0x9c8e48,'bypass_hdr_process: use legacy matrix/LUT branch, no HDR2 shortcut'),
)

def prepare(source,out):
    raw=source.read_bytes()
    assert hashlib.sha256(raw).hexdigest()==PIN,'Unmatched Image'
    changed=bytearray(raw);rows=[]
    for off,expected,target,purpose in CHANGES:
        assert struct.unpack_from('<I',raw,off)[0]==expected,(hex(off),'opcode mismatch')
        # Each original selector is immediately preceded by cmp w0,#0x27.
        assert struct.unpack_from('<I',raw,off-4)[0]==0x71009c1f
        delta=((expected>>5)&0x7ffff)
        if delta&(1<<18):delta-=1<<19
        old_target=off+delta*4
        if target is None:
            new=0xd503201f # NOP: preserve old <=G12A fall-through
        else:
            assert old_target==target
            distance=target-off
            assert distance%4==0 and -(1<<27)<=distance<(1<<27)
            new=0x14000000|((distance//4)&0x3ffffff)
        struct.pack_into('<I',changed,off,new)
        rows.append(dict(offset=hex(off),old=hex(expected),new=hex(new),target=hex(target or off+4),purpose=purpose))
    allowed={off+i for off,*_ in CHANGES for i in range(4)}
    assert len(changed)==len(raw)
    assert all(a==b or i in allowed for i,(a,b) in enumerate(zip(raw,changed)))
    assert not out.exists();out.mkdir(parents=True)
    (out/'e900-Image293L').write_bytes(changed)
    (out/'provenance.json').write_text(json.dumps(dict(source_sha256=PIN,trial_sha256=hashlib.sha256(changed).hexdigest(),changes=rows,
        scope='SDR CSC legacy route experiment on this GXLX2 box only; other format helpers not exhaustively changed',
        generic_soc_guard=False,hardware_tested=False),indent=2)+'\n')
    print(f'Prepared {len(CHANGES)}-branch / {len(CHANGES)*4}-byte-slot trial; original Image unchanged')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();prepare(a.source,a.output)
