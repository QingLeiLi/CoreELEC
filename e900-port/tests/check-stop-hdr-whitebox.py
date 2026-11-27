#!/usr/bin/env python3
"""Execute actual HDR control RMW fragments and index the recorded A/B writes.

This proves software's transformation, not the GXLX2 silicon bit semantics.
No device access, kernel mutation, or hardware-pixel assertions.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

P=Path(__file__).resolve().parents[1]
A=Path(os.environ.get('E900_AUDIT_ROOT',P.parent/'coreelec-audit'))
name='drivers/amlogic/media/enhancement/amvecm/set_hdr2_v0.c'
source=A/'sources'/name.replace('/','__')
s=source.read_text()
fixture=next(r for r in json.loads((P/'tests/source-fixtures.json').read_text()) if r['path']==name)
assert hashlib.sha256(source.read_bytes()).hexdigest()==fixture['sha256']
header=(A/'sources'/('drivers/amlogic/media/enhancement/amvecm/set_hdr2_v0.h'.replace('/','__'))).read_text()
for symbol,value in (('MTX_ONLY',1),('MTX_OFF',0),('LUT_OFF',0)):
    assert re.search(r'#define\s+'+symbol+r'\s+'+str(value)+r'\b',header),symbol


def function(name):
    m=re.search(r'^(?:static )?(?:void|u32) '+name+r'\([^;]+?\)\s*\{',s,re.M)
    assert m,name
    begin=s.index('{',m.start());end=begin+1;depth=1
    while depth:
        depth+=(s[end]=='{')-(s[end]=='}');end+=1
    return s[begin+1:end-1]


def controls(text):
    return re.findall(r'VSYNC_WRITE_VPP_REG_BITS\(hdr_ctrl,.*?\);',text,re.S)


matrix=function('set_hdr_matrix')
in_at=matrix.index('if (mtx_sel == HDR_IN_MTX)')
gamut_at=matrix.index('else if (mtx_sel == HDR_GAMUT_MTX)')
out_at=matrix.index('else if (mtx_sel == HDR_OUT_MTX)')
common=controls(matrix[:in_at]);assert len(common)==1
stages=[('matrix-in',common+controls(matrix[in_at:gamut_at])),
        ('eotf',controls(function('set_eotf_lut'))),
        ('gamut',common+controls(matrix[gamut_at:out_at])),
        ('ootf',controls(function('set_ootf_lut'))),
        ('oetf',controls(function('set_oetf_lut'))),
        ('matrix-out',common+controls(matrix[out_at:])),
        ('cgain',controls(function('set_c_gain')))]
assert [len(words) for _,words in stages]==[4,1,2,1,1,3,2]
# Guards precede LUT address/data port writes. OFF changes control enables,
# but skips LUT payload uploads; do not suggest a missing table upload here.
for name in ('set_eotf_lut','set_ootf_lut','set_oetf_lut'):
    f=function(name)
    assert f.index('if (!hdr_lut_param->lut_on)')<f.index('VSYNC_WRITE_VPP_REG(')
f=function('set_c_gain')
assert f.index('if (!hdr_lut_param->cgain_en)')<f.index('VSYNC_WRITE_VPP_REG(')
code=r'''
#include <assert.h>
#include <stdio.h>
struct matrix {unsigned mtx_on,mtx_only,mtx_gamut_mode;};
struct lut {unsigned lut_on,cgain_en;};
static unsigned ctrl=0xd05f;
static void bits(unsigned value,unsigned start,unsigned len){
 unsigned mask=((1u<<len)-1)<<start;
 ctrl=(ctrl&~mask)|((value<<start)&mask);
}
#define VSYNC_WRITE_VPP_REG_BITS(reg,val,start,len) bits(val,start,len)
int main(void){
 struct matrix matrix={0,1,1};struct lut lut={0,0};
 struct matrix *hdr_mtx_param=&matrix;struct lut *hdr_lut_param=&lut;
'''
for name,words in stages:
    code+='\n'.join(words)+'\nprintf("'+name+' %x\\n",ctrl);\n'
code+='assert(ctrl==0x1c040);assert((0xd05fu^ctrl)==0x1101f);return 0;}\n'
with tempfile.TemporaryDirectory(prefix='e900-stop-hdr-whitebox-') as directory:
    root=Path(directory);(root/'t.c').write_text(code)
    subprocess.run([shutil.which('clang') or 'cc','-std=c99','-Wall','-Wextra','-Werror',str(root/'t.c'),'-o',str(root/'t')],check=True)
    result=subprocess.check_output([str(root/'t')],text=True)
print(result,end='')

# Real A/B selected-software-write difference, not a full MMIO trace.
evidence=P/'boards/evidence/build293'
a=json.loads(gzip.decompress((evidence/'transition-stop.json.gz').read_bytes()))['records']
b=json.loads(gzip.decompress((evidence/'stop-hdr-guard-01/transition-stop.json.gz').read_bytes()))['records']
def writes(rows):
    return [r for r in rows if r['source'] in (2,3,4) and r['kind']==4 and r['phase']==2]
wa,wb=writes(a),writes(b)
only={r['reg'] for r in wa}-{r['reg'] for r in wb}
vd1={r for r in only if 0x3800<=r<=0x383f}
osd={r for r in only if 0x38a0<=r<=0x38df}
assert len(vd1)==39 and len(osd)==39 and only-(vd1|osd)=={0x3d6d}
assert not [r for r in b if r['source'] in (2,3,4) and r['kind']==4 and 0x3800<=r['reg']<=0x38ff]
assert any(r['reg']==0x3800 and r['value']==0x1c040 for r in wa)
print('PASS: source RMW produces d05f -> 1c040; bypass skips LUT payload writes; A-only addresses split 39 VD1 + 39 OSD + 1 wrap. Hardware meaning/causality of a particular bit remains unproved.')
