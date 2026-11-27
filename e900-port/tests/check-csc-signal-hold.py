#!/usr/bin/env python3
"""Execute production pre-processing/hold prefix; SDR signal helper is isolated."""
from pathlib import Path
import subprocess,tempfile
import os,json,shutil
P=Path(__file__).resolve().parents[1]
A=Path(os.environ.get('E900_AUDIT_ROOT',P.parent/'coreelec-audit'))
# Real pinned amcsc plus the production patch stack; no substitute policy.
with tempfile.TemporaryDirectory(prefix='e900-csc-source-') as temp:
 d=Path(temp)
 for row in json.loads((P/'tests/source-fixtures.json').read_text()):
  if row['repo']!='CoreELEC/linux-amlogic':continue
  dst=d/row['path'];dst.parent.mkdir(parents=True,exist_ok=True)
  shutil.copyfile(A/'sources'/row['path'].replace('/','__'),dst)
 for patch in sorted((P/'patches/linux').glob('*.patch')):
  subprocess.run(['git','apply',str(patch)],cwd=d,check=True)
 subprocess.run(['git','apply',str(P/'candidates/0044-gxlx2-defer-signal-cache-while-layer-held.patch')],cwd=d,check=True)
 s=(d/'drivers/amlogic/media/enhancement/amvecm/amcsc.c').read_text()
a=s.index('static int vpp_matrix_update('); b=s.index('\n\tif (is_dolby_vision_on() &&',a)
prefix=s[a:b]+'\n (void)csc_type;\n return signal_change_flag;\n}\n'
assert prefix.index('e900-csc-defer-signal-cache:') < prefix.index('signal_type_changed(vf, vinfo, vd_path)')
pre=r'''
#include <assert.h>
#include <stdbool.h>
#include <string.h>
#define VD_PATH_MAX 2
struct hdr_info {int x;};
#define VD1_PATH 0
#define VD2_PATH 1
#define HDR_MODULE_BYPASS 2
#define HDR_MODULE_ON 1
#define PROC_FLAG_FORCE_PROCESS 1
#define VMODE_NULL 0
#define VMODE_INVALID 1
#define MESON_CPU_MAJOR_ID_G12A 0x28
#define SIG_PRI_INFO 2
#define SIG_CS_CHG 4
#define SIG_FORCE_CHG 8
#define CSC_FLAG_CHECK_OUTPUT 1
#define CSC_FLAG_TOGGLE_FRAME 2
#define CSC_FLAG_FORCE_SIGNAL 4
#define pr_csc(...) ((void)0)
#define e900_playback_note(...) ((void)0)
enum vd_path_e {PATH0,PATH1};
enum vpp_matrix_csc_e {VPP_MATRIX_NULL};
enum hdr_type_e {HDRTYPE_NONE};
struct vframe_master_display_colour_s {int x;};
struct vframe_s {int signal;};
struct vinfo_s {int mode,hdr_info;};
static struct vframe_master_display_colour_s cur_master_display_colour[2];
static int receiver_hdr_info,cur_csc_type[2],video_process_flags[2],video_process_status[2];
static int force_csc_type=0xff,video_layer_wait_on[2];
static int cur_signal_type[2],layer_on,signal_calls,dolby_on;
#define cached_signal cur_signal_type[0]
static unsigned cpu=0x2a;
static bool is_meson_gxlx2_cpu(void){return cpu==0x2a;}
static bool cpu_after_eq(int id){return cpu>=(unsigned)id;}
static void hdr_support_process(struct vinfo_s*v,int p){(void)v;(void)p;}
static int signal_type_changed(struct vframe_s*v,struct vinfo_s*i,int vd_path){
 (void)i;signal_calls++;
 int signal_type=v->signal,change_flag=0;
 /* E900_REAL_SIGNAL_CACHE_BLOCK */
 return change_flag;
}

static void get_cur_vd_signal_type(int p){(void)p;}
static int get_csc_type(void){return 0;}
static int is_video_layer_on(int p){(void)p;return layer_on;}
static int is_dolby_vision_on(void){return dolby_on;}
'''
# Use the production cache mutation too; normalization and other signal
# properties are outside this narrow reproducer, explicitly not full HDR.
start=s.index('\tif (signal_type != cur_signal_type[vd_path]) {')
end=s.index('\n\tif (pre_src_type',start)
pre=pre.replace('/* E900_REAL_SIGNAL_CACHE_BLOCK */',s[start:end])
main=r'''
int main(void){
 struct vframe_s vf={9}; struct vinfo_s vi={2,0};
 video_process_status[0]=HDR_MODULE_BYPASS;cached_signal=0;
 assert(vpp_matrix_update(&vf,&vi,CSC_FLAG_CHECK_OUTPUT,PATH0)==2);
 assert(signal_calls==0 && cached_signal==0);
 layer_on=1;
 assert(vpp_matrix_update(&vf,&vi,CSC_FLAG_TOGGLE_FRAME,PATH0)==SIG_CS_CHG);
 assert(signal_calls==1 && cached_signal==9);
 /* Identical fake/real SDR metadata produces NO pending change even
  * with this fix. It does not invalidate a BYPASS hardware transaction.
  * This counterexample prevents promoting cache deferral to black fix. */
 layer_on=0;cached_signal=9;signal_calls=0;video_process_status[0]=HDR_MODULE_BYPASS;
 assert(vpp_matrix_update(&vf,&vi,CSC_FLAG_CHECK_OUTPUT,PATH0)==2);
 assert(signal_calls==0);
 layer_on=1;
 assert(vpp_matrix_update(&vf,&vi,CSC_FLAG_TOGGLE_FRAME,PATH0)==0);
 /* Other CPUs preserve the upstream cache/hold behavior. */
 for(cpu=0x20;cpu<=0x40;cpu++){
  if(cpu==0x2a)continue;
  layer_on=0;signal_calls=0;cached_signal=0;
  video_process_status[0]=HDR_MODULE_BYPASS;
  assert(vpp_matrix_update(&vf,&vi,CSC_FLAG_CHECK_OUTPUT,PATH0)==2);
  assert(signal_calls==1 && cached_signal==9);
 }
 cpu=0x2a;
 /* Force-processing, wait-on, normal-on and VD2 are unchanged. */
 for(int mode=0;mode<3;mode++){
  layer_on=mode==2;video_layer_wait_on[0]=mode==1;
  video_process_flags[0]=mode==0?PROC_FLAG_FORCE_PROCESS:0;
  video_process_status[0]=HDR_MODULE_BYPASS;
  signal_calls=0;cached_signal=0;
  assert(vpp_matrix_update(&vf,&vi,CSC_FLAG_TOGGLE_FRAME,PATH0)==SIG_CS_CHG);
  assert(signal_calls==1);
 }
 layer_on=0;signal_calls=0;cached_signal=0;video_process_status[1]=HDR_MODULE_BYPASS;
 assert(vpp_matrix_update(&vf,&vi,CSC_FLAG_CHECK_OUTPUT,PATH1)==2);
 assert(signal_calls==1);
 /* DV-held VD1 also must not consume; on but no longer BYPASS proceeds. */
 dolby_on=1;layer_on=1;video_process_status[0]=HDR_MODULE_BYPASS;
 signal_calls=0;cached_signal=0;
 assert(vpp_matrix_update(&vf,&vi,CSC_FLAG_CHECK_OUTPUT,PATH0)==2);
 assert(signal_calls==0);
 dolby_on=0;video_process_status[0]=HDR_MODULE_ON;
 assert(vpp_matrix_update(&vf,&vi,CSC_FLAG_TOGGLE_FRAME,PATH0)==SIG_CS_CHG);
 return 0;
}
'''
with tempfile.TemporaryDirectory() as d:
 p=Path(d);(p/'t.c').write_text(pre+prefix+main)
 subprocess.run(['clang','-std=gnu99','-Wall','-Werror','-Wno-unused-variable',str(p/'t.c'),'-o',str(p/'t')],check=True)
 subprocess.run([str(p/'t')],check=True)
 # Negative control: remove only the candidate block, execute the SAME
 # production prefix and demonstrate that off consumes the next CS change.
 begin=prefix.index('\n\t/* e900-csc-defer-signal-cache:')
 end=prefix.index('\n\t/* e900-csc-defer-signal-cache end */',begin)
 end=prefix.index('\n',end+1)
 old=prefix[:begin]+prefix[end:]
 baseline=r'''
int main(void){
 struct vframe_s vf={9};struct vinfo_s vi={2,0};
 assert(is_meson_gxlx2_cpu());
 video_process_status[0]=HDR_MODULE_BYPASS;
 assert(vpp_matrix_update(&vf,&vi,CSC_FLAG_CHECK_OUTPUT,PATH0)==2);
 assert(signal_calls==1 && cached_signal==9);
 layer_on=1;
 assert(vpp_matrix_update(&vf,&vi,CSC_FLAG_TOGGLE_FRAME,PATH0)==0);
 return 0;
}
'''
 (p/'t.c').write_text(pre+old+baseline)
 subprocess.run(['clang','-std=gnu99','-Wall','-Werror','-Wno-unused-variable',str(p/'t.c'),'-o',str(p/'t')],check=True)
 subprocess.run([str(p/'t')],check=True)
print('PASS: real CSC prefix defers GXLX2 VD1 cache while held; on/wait/force/VD2 and other CPU paths preserved. Production signal-cache block exercised; identical-metadata counterexample remains unfixed; full HDR/ARM/hardware pending.')
