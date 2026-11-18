#!/usr/bin/env python3
"""Compare real upstream/patched matrix I/O traces across CPU/selector/mode cases."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

PORT=Path(__file__).resolve().parents[1]
AUDIT=Path(os.environ.get('E900_AUDIT_ROOT',PORT.parent/'coreelec-audit'))
FILE='drivers/amlogic/media/enhancement/amvecm/set_hdr2_v0.c'

def function(source,name):
    start=source.index('void '+name+'(');body=source.index('{',start);depth=1;end=body+1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[start:end]+'\n'

def enum(source,name):
    start=source.index('enum '+name+' {');end=source.index('};',start)+2
    return source[start:end]+'\n'

with tempfile.TemporaryDirectory(prefix='e900-post2-') as tmp:
    root=Path(tmp);dest=root/FILE;dest.parent.mkdir(parents=True)
    original=(AUDIT/'sources'/FILE.replace('/','__')).read_text();dest.write_text(original)
    subprocess.run(['git','apply',str(PORT/'patches/linux/0007-gxlx2-post2-matrix-guard.patch')],cwd=root,check=True)
    patched=dest.read_text()
    funcs=['mtx_setting','mtx_init']
    old=''.join(function(original,f).replace('void '+f+'(','void baseline_'+f+'(') for f in funcs)
    new=''.join(function(patched,f) for f in funcs)
    registers=sorted(set(re.findall(r'\bVPP_[A-Z0-9_]+\b',old+new)))
    # Unique register tokens are enough to prove unchanged writes; this is not
    # a hardware register-map test. Compare the complete baseline I/O sequence.
    harness='''#include <assert.h>
#include <stdbool.h>
#include <string.h>
#include <stdint.h>
struct op {unsigned kind,reg,val,start,width;};
static struct op calls[256];static unsigned count,cpu,disable_flush_flag;
static bool is_meson_gxlx2_cpu(void){return cpu==0x2a;}
static void record(unsigned kind,unsigned reg,unsigned val,unsigned start,unsigned width){
 assert(count<256);calls[count++]=(struct op){kind,reg,val,start,width};
}
#define VSYNC_WRITE_VPP_REG(r,v) record(1,r,v,0,0)
#define VSYNC_WRITE_VPP_REG_BITS(r,v,s,w) record(2,r,v,s,w)
'''
    harness+=enum((AUDIT/'sources/include__linux__amlogic__media__amvecm__amvecm.h').read_text(),'vpp_matrix_e')
    harness+=enum((AUDIT/'sources/drivers__amlogic__media__enhancement__amvecm__set_hdr2_v0.h').read_text(),'mtx_csc_e')
    harness+=''.join('#define '+name+' '+str(0x1000+i)+'\n' for i,name in enumerate(registers))
    harness+=old+new+'''
int main(void){
 const unsigned cpus[]={0x21,0x28,0x2a,0x2b};const unsigned selectors[]={VD1_MTX,POST2_MTX,POST_MTX};
 struct op expected[256];
 for(unsigned c=0;c<4;c++)for(unsigned s=0;s<3;s++)for(unsigned on=0;on<2;on++)
 for(unsigned flush=0;flush<2;flush++)for(unsigned mode=0;mode<=0x42;mode++)for(unsigned init=0;init<2;init++){
  cpu=cpus[c];disable_flush_flag=flush;count=0;
  if(init)baseline_mtx_init(selectors[s],mode,on);else baseline_mtx_setting(selectors[s],mode,on);
  unsigned n=count;memcpy(expected,calls,n*sizeof(*calls));count=0;
  if(init)mtx_init(selectors[s],mode,on);else mtx_setting(selectors[s],mode,on);
  if(cpu==0x2a && selectors[s]==POST2_MTX){assert(count==0);}
  else{assert(count==n);assert(memcmp(expected,calls,n*sizeof(*calls))==0);}
 }
 return 0;
}
'''
    c=root/'test.c';c.write_text(harness);compiler=shutil.which('clang') or shutil.which('cc')
    subprocess.run([compiler,'-std=c99','-Wall','-Werror','-Wno-unused-but-set-variable',str(c),'-o',str(root/'test')],check=True)
    subprocess.run([str(root/'test')],check=True)
print('PASS: real matrix functions suppress only GXLX2 POST2; all other CPU/selector writes match upstream byte-for-byte')
print('PASS: both initializer/setting, on/off, flush state and all matrix modes exercised; hardware map/full ARM build not covered')
