#!/usr/bin/env python3
"""Compile real wrapper bodies, preserving null/unsupported dispatch behavior."""
import json,os,subprocess,tempfile,shutil
from pathlib import Path
PORT=Path(__file__).resolve().parents[1]
AUDIT=Path(os.environ.get('E900_AUDIT_ROOT',PORT.parent/'coreelec-audit'))
with tempfile.TemporaryDirectory(prefix='e900-calls-') as folder:
 root=Path(folder)
 for row in json.loads((PORT/'tests/source-fixtures.json').read_text()):
  if row['repo']=='CoreELEC/linux-amlogic':
   p=root/row['path'];p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(AUDIT/'sources'/row['path'].replace('/','__'),p)
 for patch in sorted((PORT/'patches/linux').glob('*.patch')):subprocess.run(['git','apply',str(patch)],cwd=root,check=True)
 src=(root/'drivers/amlogic/media/video_sink/video_hw.c').read_text()
 def function(name):
  a=src.index('void '+name+'(');b=src.index('{',a);i=b+1;depth=1
  while depth:depth+=(src[i]=='{')-(src[i]=='}');i+=1
  return src[a:i]
 c=r'''
#include <assert.h>
#include <stdbool.h>
typedef unsigned char u8;
struct video_layer_s {int unused;};struct vpp_frame_par_s{int unused;};struct vframe_s{int unused;};
struct scaler_setting_s{bool support;};
static unsigned events[16],n,dcu1,dcu2,pps1,pps2;
static unsigned e900_hdr_recovery_video_session(void){return 1;}
static void e900_playback_note(unsigned s,unsigned k,unsigned session,unsigned b,unsigned h,unsigned r,unsigned v,unsigned a){assert(s==1&&k==2&&session==1);(void)b;(void)h;(void)v;(void)a;events[n++]=r;}
#define DCU(name,counter) static void name(struct video_layer_s*l,struct vpp_frame_par_s*p,struct vframe_s*v){(void)l;(void)p;(void)v;counter++;}
DCU(vd1_set_dcu,dcu1) DCU(vd2_set_dcu,dcu2)
static void vd1_scaler_setting(struct scaler_setting_s*s){(void)s;pps1++;}
static void vd2_scaler_setting(struct scaler_setting_s*s){(void)s;pps2++;}
''' + function('vd_set_dcu')+'\n'+function('vd_scaler_setting')+r'''
int main(void){struct scaler_setting_s s={false};
 vd_set_dcu(0,0,0,0);assert(dcu1==1&&n==2&&events[0]==11&&events[1]==12);
 vd_set_dcu(1,0,0,0);assert(dcu2==1&&n==2);
 n=0;vd_scaler_setting(0,&s);assert(pps1==0&&n==2&&events[0]==13&&events[1]==15);
 n=0;s.support=true;vd_scaler_setting(0,&s);assert(pps1==1&&n==2&&events[1]==14);
 n=0;vd_scaler_setting(1,&s);assert(pps2==1&&n==0);
 vd_scaler_setting(0,0);assert(pps1==2);return 0;}
'''
 (root/'test.c').write_text(c)
 subprocess.run(['cc','-std=gnu89','-Wall','-Werror',str(root/'test.c'),'-o',str(root/'test')],check=True)
 subprocess.run([str(root/'test')],check=True)
print('PASS: real DCU/PPS wrappers preserve dispatch and unsupported/null behavior; only VD1 records paired entry/exit/skip')
