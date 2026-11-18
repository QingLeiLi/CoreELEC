#!/usr/bin/env python3
"""Pin-checked GXLX2-only VLD DMC mask trial in the existing decoder module."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

PINNED='c4c355cfcce7406ed11ab30b0b831ce1642a51d2f9e497829190d779acaa0fdf'
# Same source VLD-mask selection, inlined in init/release plus exported reset.
PATCHES=[('vdec_init',0x5364,26),('vdec_reset_core',0x5f80,19),('vdec_release',0x7bdc,19)]

def make(source,output):
    assert not output.exists()
    original=source.read_bytes();assert hashlib.sha256(original).hexdigest()==PINNED
    assert original[:6]==b'\x7fELF\x02\x01' and struct.unpack_from('<H',original,18)[0]==183
    shoff=struct.unpack_from('<Q',original,40)[0]
    entsize,count,stridx=struct.unpack_from('<HHH',original,58)
    assert entsize==64
    sections=[struct.unpack_from('<IIQQQQIIQQ',original,shoff+i*entsize) for i in range(count)]
    names=original[sections[stridx][4]:sections[stridx][4]+sections[stridx][5]]
    text=next(s for s in sections if names[s[0]:].split(b'\0',1)[0]==b'.text')
    patched=bytearray(original);changes=[]
    for function,offset,reg in PATCHES:
        assert offset+4<=text[5]
        pos=text[4]+offset
        before=0x52a00400|reg;after=0x52840000|reg
        assert struct.unpack_from('<I',original,pos)[0]==before,(function,hex(offset))
        struct.pack_into('<I',patched,pos,after)
        changes.append(dict(function=function,text_offset=offset,file_offset=pos,before=hex(before),after=hex(after)))
    changed={i for i,(a,b) in enumerate(zip(original,patched)) if a!=b}
    assert changed=={c['file_offset']+i for c in changes for i in [1,2]}
    output.mkdir(parents=True)
    (output/'decoder_common.ko').write_bytes(patched)
    (output/'dmc-provenance.json').write_text(json.dumps({'original_sha256':PINNED,'patched_sha256':hashlib.sha256(patched).hexdigest(),'scope':'GXLX2 VLD mask bit21 to bit13; no firmware or HEVC changes','instructions':changes,'hardware_tested':False,'not_for_other_boards':True},indent=2)+'\n')
    print('Prepared three-instruction DMC candidate; all other ELF bytes and relocations unchanged')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();make(a.source,a.output)
