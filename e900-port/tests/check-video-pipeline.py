#!/usr/bin/env python3
"""Compile real initialization selection blocks; this is not a full kernel build."""
import hashlib,json,os,re,shutil,subprocess,tempfile,textwrap
from pathlib import Path
PORT=Path(__file__).resolve().parents[1]
AUDIT=Path(os.environ.get('E900_AUDIT_ROOT',PORT.parent/'coreelec-audit'))
FILE='drivers/amlogic/media/video_sink/video_hw.c'
row=next(r for r in json.loads((PORT/'tests/source-fixtures.json').read_text()) if r['path']==FILE)
original=(AUDIT/'sources'/FILE.replace('/','__')).read_text()
assert hashlib.sha256(original.encode()).hexdigest()==row['sha256']
def selections(source):
    init=source.index('int video_early_init(')
    a=source.index('\tif (cpu_after_eq(MESON_CPU_MAJOR_ID_G12A)',init)
    b=source.index('legacy_vpp = false;',a)+len('legacy_vpp = false;')
    c=source.index('\t\tif (cpu_after_eq(MESON_CPU_MAJOR_ID_G12A)',b)
    p=source.index('{',c);depth=1;q=p+1
    while depth:
        depth+=(source[q]=='{')-(source[q]=='}');q+=1
    e=source.index('{',q);depth=1;q=e+1
    while depth:
        depth+=(source[q]=='{')-(source[q]=='}');q+=1
    # The snippets came from different nesting depths. Normalize each one
    # independently before placing both at the same harness function scope.
    return textwrap.indent('\n'.join(textwrap.dedent(part)
                                    for part in (source[a:b],source[c:q])), '    ')
with tempfile.TemporaryDirectory(prefix='e900-video-policy-') as tmp:
    root=Path(tmp);dest=root/FILE;dest.parent.mkdir(parents=True);dest.write_text(original)
    subprocess.run(['git','apply',str(PORT/'patches/linux/0008-gxlx2-legacy-video-pipeline.patch')],cwd=root,check=True)
    patched=dest.read_text()
    old=selections(original);new=selections(patched)
    # Blocks are separated in the file, so verify each edit independently.
    restored=patched.replace('#include <linux/amlogic/cpu_version.h>\n','').replace('\t/* P291 uses the legacy VPP/OSD profile despite its numeric CPU ID. */\n','')
    restored=re.sub(r'(cpu_after_eq\(MESON_CPU_MAJOR_ID_G12A\)) &&\n\s*!is_meson_gxlx2_cpu\(\)',r'\1',restored)
    assert restored==original
    c=root/'test.c';c.write_text('''#include <assert.h>
#include <stdbool.h>
#include <string.h>
#define MESON_CPU_MAJOR_ID_G12A 0x28
static unsigned cpu;static bool revb,legacy_vpp;
static bool cpu_after_eq(unsigned x){return cpu>=x;}
static bool is_meson_gxlx2_cpu(void){return cpu==0x2a;}
static bool is_meson_tm2_revb(void){return revb;}
struct hw_vd_reg_s {unsigned values[8];};
struct hw_fg_reg_s {unsigned values[4];};
static struct {struct hw_vd_reg_s vd_mif_reg;struct hw_fg_reg_s fg_reg;} vd_layer[2];
static struct hw_vd_reg_s vd_mif_reg_g12_array[2],vd_mif_reg_legacy_array[2];
static struct hw_fg_reg_s fg_reg_g12_array[2];
static void baseline(void){
'''+old+'\n}\nstatic void candidate(void){\n'+new+'''
}
int main(void){
 memset(vd_mif_reg_g12_array,0x12,sizeof vd_mif_reg_g12_array);
 memset(vd_mif_reg_legacy_array,0x21,sizeof vd_mif_reg_legacy_array);
 memset(fg_reg_g12_array,0x34,sizeof fg_reg_g12_array);
 for(cpu=0;cpu<0x40;cpu++)for(unsigned r=0;r<2;r++){
  unsigned char expected[sizeof vd_layer];bool expected_legacy;
  revb=r;legacy_vpp=true;memset(vd_layer,0,sizeof vd_layer);baseline();
  memcpy(expected,vd_layer,sizeof vd_layer);expected_legacy=legacy_vpp;
  legacy_vpp=true;memset(vd_layer,0,sizeof vd_layer);candidate();
  if(cpu==0x2a){
   assert(legacy_vpp);
   for(unsigned i=0;i<2;i++){
    assert(!memcmp(&vd_layer[i].vd_mif_reg,&vd_mif_reg_legacy_array[i],sizeof(struct hw_vd_reg_s)));
    struct hw_fg_reg_s zero={0};assert(!memcmp(&vd_layer[i].fg_reg,&zero,sizeof zero));
   }
  }else{assert(legacy_vpp==expected_legacy);assert(!memcmp(expected,vd_layer,sizeof vd_layer));}
 }
 return 0;
}
''')
    subprocess.run([shutil.which('clang') or 'cc','-std=c99','-Wall','-Wmisleading-indentation','-Werror',str(c),'-o',str(root/'test')],check=True)
    subprocess.run([str(root/'test')],check=True)
print('PASS: actual VPP/MIF initialization blocks select legacy for GXLX2; all other CPU IDs and revision states match upstream')
print('PENDING: full ARM compilation, remaining family checks and physical playback')
