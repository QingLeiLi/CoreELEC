#!/usr/bin/env python3
"""Verify HDR hooks preserve policy and execute the actual boundary blocks."""
import json, os, re, shutil, subprocess, tempfile
from pathlib import Path
P = Path(__file__).resolve().parents[1]
A = Path(os.environ.get('E900_AUDIT_ROOT', P.parent/'coreelec-audit'))
name = 'drivers/amlogic/media/enhancement/amvecm/set_hdr2_v0.c'
with tempfile.TemporaryDirectory(prefix='e900-hdr-evidence-') as td:
    root = Path(td)
    for row in json.loads((P/'tests/source-fixtures.json').read_text()):
        if row['repo'] == 'CoreELEC/linux-amlogic':
            f = root/row['path']; f.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(A/'sources'/row['path'].replace('/', '__'), f)
    for patch in sorted((P/'patches/linux').glob('*.patch')):
        if patch.name.startswith('0033-'):
            before = (root/name).read_text()
        subprocess.run(['git', 'apply', str(patch)], cwd=root, check=True)
    after = (root/name).read_text()
    stripped = after
    # Remove only the four explicit calls, not an arbitrary C block.
    for event in ('hdr_flush_disabled', 'hdr_request', 'hdr_osd_wrap_off', 'hdr_submitted'):
        stripped, n = re.subn(r'^\t+e900_debug_event\("'+event+r'"[^;]+;\n', '', stripped, flags=re.M)
        assert n == 1, event
    stripped = stripped.replace('#include <linux/amlogic/media/registers/e900_debug.h>\n', '')
    stripped = stripped.replace('/* Default-off bounded software events; submitted is not hardware completion. */\nE900_DEBUG_CHANNEL("hdr")\n\n', '')
    stripped = stripped.replace('\tif (disable_flush_flag) {\n\t\treturn hdr_process_select;\n\t}', '\tif (disable_flush_flag)\n\t\treturn hdr_process_select;')
    assert stripped == before, 'Non-diagnostic HDR policy changes'
    func = after.split('enum hdr_process_sel hdr_func(', 1)[1].split('\nu32 hdr_set(', 1)[0]
    entry = func[func.index('\tif (disable_flush_flag)'):func.index('\tmemset(&hdr_mtx_param')]
    wrap = func[func.index('\tif ((module_sel == OSD1_HDR)'):func.index('\tif (cpu_after_eq(MESON_CPU_MAJOR_ID_TM2))')]
    tail = func[func.index('\tset_hdr_matrix(module_sel, HDR_IN_MTX'):func.rindex('}')]
    c = r'''
#include <assert.h>
#include <stdbool.h>
#include <string.h>
typedef unsigned u32;
#define OSD1_HDR 2
#define MESON_CPU_MAJOR_ID_G12A 0x28
#define RGB_OSD 0x100
#define VPP_WRAP_OSD1_MATRIX_EN_CTRL 42
#define HDR_IN_MTX 1
#define HDR_GAMUT_MTX 2
#define HDR_OUT_MTX 3
static unsigned cpu,disable_flush_flag,events,step,wrap_writes;
static bool dv,tv;
struct param {unsigned lut_on,mtx_on;};
static struct param hdr_lut_param,hdr_mtx_param;
static bool cpu_after_eq(unsigned n){return cpu>=n;}
static bool is_meson_g12a_cpu(void){return cpu==0x28;}
static bool is_meson_g12b_cpu(void){return cpu==0x29;}
static bool is_meson_rev_a(void){return true;}
static bool is_dolby_vision_on(void){return dv;}
static bool is_hdr_tvmode(void){return tv;}
static void e900_debug_event(const char*s,unsigned a,unsigned b,unsigned c,unsigned d){
 (void)a;(void)b;(void)c;(void)d;events++;
 if(!strcmp(s,"hdr_submitted"))assert(step==8);
}
#define VSYNC_WRITE_VPP_REG(r,v) do{assert((r)==42&&(v)==0);wrap_writes++;}while(0)
static void set_hdr_matrix(unsigned m,unsigned sel,struct param*p,void*n){
 (void)m;(void)p;(void)n;assert((step==0&&sel==1)||(step==2&&sel==2)||(step==5&&sel==3));step++;
}
#define HELPER(name,expected) static void name(unsigned m,struct param*p){(void)m;(void)p;assert(step==expected);step++;}
HELPER(set_eotf_lut,1)
HELPER(set_ootf_lut,3)
HELPER(set_oetf_lut,4)
HELPER(set_c_gain,6)
HELPER(hdr_hist_config,7)
static u32 exercise(unsigned module_sel,u32 hdr_process_select){
 bool always_full_func=false;
''' + entry + wrap + '(void)always_full_func;\n' + tail + r'''
}
int main(void){
 unsigned chips[]={0x21,0x28,0x29,0x2a,0x2b},i,m,f;
 for(i=0;i<5;i++)for(m=0;m<3;m++)for(f=0;f<2;f++){
  unsigned result;cpu=chips[i];disable_flush_flag=f;events=step=wrap_writes=0;
  dv=false;tv=false;result=exercise(m,1);
  if(f){assert(result==1&&events==1&&!step&&!wrap_writes);}
  else {bool w=m==OSD1_HDR&&cpu>=0x28;assert(result==(1|(w?RGB_OSD:0))&&step==8&&wrap_writes==w&&events==(w?3u:2u));}
 }
 return 0;
}
'''
    (root/'test.c').write_text(c)
    for std in ('gnu89', 'gnu99'):
        subprocess.run([shutil.which('clang') or 'cc', '-std='+std, '-Wall', '-Wextra', '-Werror', str(root/'test.c'), '-o', str(root/'test')], check=True)
        subprocess.run([str(root/'test')], check=True)
print('PASS: HDR policy byte-for-byte preserved after removing diagnostics; actual flush/wrap/submission blocks exercised; hardware completion not claimed')
