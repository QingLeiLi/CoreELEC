#!/usr/bin/env python3
"""One-branch GXLX2-only diagnostic: return before POST2 matrix register access."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

PINNED={'2126e5a3aac587db015ec3bb879421c28ae045dccf24f12361f653bcbe3a11b8',
        '216ae053e607f32986ffa0c92d43803938e0e75cc044dc4302ec9ff1b9163029'}
HOOK=0x977d1c
RETURN=0x977dfc

def make(source,output):
    assert not output.exists()
    original=source.read_bytes();source_sha=hashlib.sha256(original).hexdigest();assert source_sha in PINNED
    assert struct.unpack_from('<I',original,HOOK-4)[0]==0x71000a7f  # cmp w19,#2 (POST2_MTX)
    old=struct.unpack_from('<I',original,HOOK)[0];assert old==0x540007e0
    assert HOOK+(((old>>5)&0x7ffff)<<2)==0x977e18
    # This existing exit restores every register saved before the selector test.
    assert struct.unpack_from('<7I',original,RETURN)==(0xa94153f3,0xa9425bf5,0xa94363f7,0xa9446bf9,0xa94573fb,0xa8c67bfd,0xd65f03c0)
    delta=RETURN-HOOK;assert delta%4==0 and 0<=delta<(1<<20)
    new=0x54000000|((delta//4)<<5)  # b.eq; preserve condition, change only its target
    patched=bytearray(original);struct.pack_into('<I',patched,HOOK,new)
    assert original[:HOOK]==patched[:HOOK] and original[HOOK+4:]==patched[HOOK+4:]
    assert len(patched)==len(original)
    output.mkdir(parents=True);target=output/'e900-Image-post2';target.write_bytes(patched)
    sha=hashlib.sha256(patched).hexdigest()
    (output/'SHA256SUMS').write_text(sha+'  e900-Image-post2\n')
    (output/'post2-provenance.json').write_text(json.dumps({'source_sha256':source_sha,'kernel_sha256':sha,'hook_offset':HOOK,'old_instruction':hex(old),'new_instruction':hex(new),'return_offset':RETURN,'changed_instructions':1,'scope':'GXLX2 diagnostic artifact only: skip POST2_MTX selector2, retain all other matrix selectors and all remaining kernel bytes','generic_soc_guard':False,'hardware_tested':False},indent=2)+'\n')
    print('Prepared one-branch POST2 diagnostic; existing complete register/stack restoration preserved')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();make(a.source,a.output)
