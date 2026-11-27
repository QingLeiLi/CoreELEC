#!/usr/bin/env python3
"""Document/execute remaining format-helper CPU gates against real HLG evidence.

This is an audit regression, NOT a claim those unmodified G12 gates are correct.
"""
import gzip,json,os,re,shutil,subprocess,tempfile
from pathlib import Path
P=Path(__file__).resolve().parents[1]
A=Path(os.environ.get('E900_AUDIT_ROOT',P.parent/'coreelec-audit'))
FILE='drivers/amlogic/media/enhancement/amvecm/amcsc.c'

def function(s,name):
    m=re.search(r'^static (?:void|int) '+name+r'\([^;]*?\)\s*\{',s,re.M);assert m,name
    a=s.index('{',m.start());b=a+1;depth=1
    while depth:depth+=(s[b]=='{')-(s[b]=='}');b+=1
    return s[a:b]

with tempfile.TemporaryDirectory(prefix='e900-hdr-helper-audit-') as td:
    root=Path(td)
    for r in json.loads((P/'tests/source-fixtures.json').read_text()):
        if r['repo']=='CoreELEC/linux-amlogic':
            dst=root/r['path'];dst.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(A/'sources'/r['path'].replace('/','__'),dst)
    for patch in sorted((P/'patches/linux').glob('*.patch')):
        subprocess.run(['git','apply',str(patch)],cwd=root,check=True)
    s=(root/FILE).read_text();predicates=[]
    for name in ('hdr_process','hdr10p_process','hlg_process','hlg_hdr_process','sdr_hdr_process'):
        f=function(s,name)
        match=re.search(r'if \((get_cpu_type\(\) >= MESON_CPU_MAJOR_ID_G12A)\) \{',f)
        assert match,name+' no longer has the audited unguarded entry; revise scope/evidence table'
        predicates.append(match[1]);print('remaining G12 entry:',name)
    code='''#include <assert.h>
#define MESON_CPU_MAJOR_ID_G12A 0x28
static unsigned cpu;
static unsigned get_cpu_type(void){return cpu;}
int main(void){
'''
    for cpu in (0x21,0x28,0x2a):
        code+=f'cpu={cpu};\n'
        for expr in predicates:code+=f'assert(({expr})=={int(cpu>=0x28)});\n'
    code+='return 0;}\n';(root/'test.c').write_text(code)
    subprocess.run([shutil.which('clang') or 'cc','-std=gnu89','-Wall','-Wextra','-Werror',str(root/'test.c'),'-o',str(root/'test')],check=True)
    subprocess.run([str(root/'test')],check=True)
    # Actual observed 0x10 call is produced by the still-unguarded HLG branch.
    f=function(s,'hlg_process');a=f.index('if (get_cpu_type() >= MESON_CPU_MAJOR_ID_G12A)')
    branch=f[a:f.index('return need_adjust_contrast_saturation;',a)]
    assert 'hdr_func(VD1_HDR, HLG_SDR | hdr_ex' in branch
    assert 'hdr_func(OSD1_HDR, HDR_BYPASS | hdr_ex' in branch
    v=function(s,'video_process')
    assert 'if (get_hdr_type() & HLG_FLAG)' in v and 'hlg_process(csc_type, vinfo, p,' in v
    assert '#define HLG_FLAG 0x1' in s
    hdr_type=function(s,'get_hdr_type')
    assert '(signal_transfer_characteristic == 18)' in hdr_type
    rows=json.loads(gzip.decompress((P/'boards/evidence/build293/hdr-formats/hlg-auto2-01/replay.json.gz').read_bytes()))['records']
    calls=[r for r in rows if r['source']==1 and r['kind']==2 and r['reg'] in (8,9)]
    assert [(r['reg'],r['handle'],r['value']) for r in calls]==[(8,1,0x10),(9,1,0x10),(8,3,1),(9,3,0x20000001)]
    words=[r for r in rows if r['source'] in(2,3,4) and r['kind']==4 and r['reg']==0x3800]
    assert [(r['index'],r['value']) for r in words]==[(146,0xe05f)]
print('PASS: current five-selector SDR fix STILL selects G12 in five HDR helpers on GXLX2; production HLG call pair matches real auto2 capture and CTRL=e05f')
print('LIMIT: no pixel-stage proof or proof of unsupported silicon; HDR10 helper execution not observed in the bypass trial')
