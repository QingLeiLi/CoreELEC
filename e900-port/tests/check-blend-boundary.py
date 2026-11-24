#!/usr/bin/env python3
"""Execute the real blend boundary helper; never claim hardware validation."""
from pathlib import Path
import json,os,re,shutil,subprocess,tempfile
P=Path(__file__).resolve().parents[1];A=Path(os.environ.get('E900_AUDIT_ROOT',P.parent/'coreelec-audit'))
def function(s,name):
 m=re.search(r'^static (?:int|u32) '+name+r'\([^;]*?\)\s*\{',s,re.M);assert m,name
 a=s.index('{',m.start());b=a+1;n=1
 while n:n+=(s[b]=='{')-(s[b]=='}');b+=1
 return s[m.start():b]
with tempfile.TemporaryDirectory(prefix='e900-blend-boundary-') as td:
 r=Path(td)
 for row in json.loads((P/'tests/source-fixtures.json').read_text()):
  if row['repo']=='CoreELEC/linux-amlogic':
   f=r/row['path'];f.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(A/'sources'/row['path'].replace('/','__'),f)
 for p in sorted((P/'patches/linux').glob('*.patch')):subprocess.run(['git','apply',str(p)],cwd=r,check=True)
 hw=(r/'drivers/amlogic/media/video_sink/video_hw.c').read_text()
 assert hw.count('vpp_misc_set = e900_blend_hold_apply(vpp_misc_set, mode, video1_off_req);')==1
 call=hw.index('vpp_misc_set = e900_blend_hold_apply');assert hw.index('force_flush |= vpp_zorder_check();')<call<hw.index('} else if (vpp_misc_save != vpp_misc_set)',call)
 c=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdlib.h>
#include <errno.h>
typedef unsigned u32;
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define COMPOSE_MODE_3D 1
#define VIDEO_ENABLE_STATE_IDLE 0
#define VIDTYPE_COMPRESS 8
#define VPP_VD1_PREBLEND (1u<<14)
#define VPP_VD1_POSTBLEND (1u<<10)
struct kernel_param {int unused;};
struct vframe_s {unsigned type;};
struct video_layer_s {struct vframe_s*dispbuf; bool vd1_vd2_mux,global_output,force_black,disable_video,enabled_status_saved,switch_vf;unsigned onoff_state;struct {unsigned vd_if0_gen_reg;}vd_mif_reg;};
static struct video_layer_s vd_layer[1];static struct {unsigned vpp_off;}dev,*cur_dev=&dev;
static unsigned gxlx2_blend_hold,cpu;static bool legacy_vpp,gxlx2_g12_mif,local;
static bool is_meson_gxlx2_cpu(void){return cpu==0x2a;}
static bool is_local_vf(struct vframe_s*v){(void)v;return local;}
static int kstrtouint(const char*s,int base,unsigned*v){char*end;unsigned long x=strtoul(s,&end,base);if(!*s||*end||x>0xfffffffful)return -EINVAL;*v=x;return 0;}
'''+function(hw,'e900_blend_hold_set')+'\n'+function(hw,'e900_blend_hold_apply')+r'''
static struct vframe_s frame;
static void reset(void){cpu=0x2a;legacy_vpp=true;gxlx2_g12_mif=local=false;dev.vpp_off=0;frame.type=0;vd_layer[0]=(struct video_layer_s){.dispbuf=&frame,.enabled_status_saved=true,.vd_mif_reg={0x1a50}};}
int main(void){
 unsigned original=0xa5a50003,mode;bool off;
 for(unsigned hold=0;hold<4;hold++){
  reset();gxlx2_blend_hold=hold;unsigned expected=original|((hold&1)?VPP_VD1_PREBLEND:0)|((hold&2)?VPP_VD1_POSTBLEND:0);
  assert(e900_blend_hold_apply(original,0,false)==expected);
  for(unsigned bad=0;bad<17;bad++){
   reset();gxlx2_blend_hold=hold;mode=0;off=false;
   switch(bad){case 0:cpu=0x21;break;case 1:legacy_vpp=false;break;case 2:gxlx2_g12_mif=true;break;case 3:vd_layer[0].vd1_vd2_mux=true;break;case 4:dev.vpp_off=1;break;case 5:mode=COMPOSE_MODE_3D;break;case 6:off=true;break;case 7:vd_layer[0].global_output=true;break;case 8:vd_layer[0].force_black=true;break;case 9:vd_layer[0].disable_video=true;break;case 10:vd_layer[0].enabled_status_saved=false;break;case 11:vd_layer[0].onoff_state=1;break;case 12:vd_layer[0].switch_vf=true;break;case 13:vd_layer[0].dispbuf=NULL;break;case 14:local=true;break;case 15:frame.type=VIDTYPE_COMPRESS;break;case 16:vd_layer[0].vd_mif_reg.vd_if0_gen_reg=0x3210;break;}
   assert(e900_blend_hold_apply(original,mode,off)==original);
  }
 }
 reset();gxlx2_blend_hold=4;assert(e900_blend_hold_apply(original,0,false)==original);
 for(unsigned i=0;i<4;i++){char text[2]={(char)('0'+i),0};assert(!e900_blend_hold_set(text,NULL)&&gxlx2_blend_hold==i);}
 assert(e900_blend_hold_set("4",NULL)==-EINVAL&&gxlx2_blend_hold==3);assert(e900_blend_hold_set("oops",NULL)==-EINVAL);
 return 0;
}
'''
 (r/'test.c').write_text(c)
 subprocess.run([shutil.which('clang') or 'cc','-std=gnu99','-Wall','-Wextra','-Werror',str(r/'test.c'),'-o',str(r/'test')],check=True)
 subprocess.run([str(r/'test')],check=True)
print('PASS: real blend helper preserves baseline, isolates pre/post and rejects17 unsafe states; ARM/hardware pending')
