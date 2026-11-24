#!/usr/bin/env python3
"""Compare real upstream/patched runtime scaler I/O, not a copy of its logic."""
from pathlib import Path
import os,re,subprocess,shutil,tempfile
P=Path(__file__).resolve().parents[1];A=Path(os.environ.get('E900_AUDIT_ROOT',P.parent/'coreelec-audit'));F='drivers/amlogic/media/video_sink/vpp.c'
def function(s):
 a=s.index('int vpp_set_super_scaler_regs(');b=s.index('{',a);i=b+1;depth=1
 while depth:depth+=(s[i]=='{')-(s[i]=='}');i+=1
 return s[a:i]+'\n'
with tempfile.TemporaryDirectory(prefix='e900-runtime-sr-') as td:
 r=Path(td);f=r/F;f.parent.mkdir(parents=True);original=(A/'sources'/F.replace('/','__')).read_text();f.write_text(original)
 subprocess.run(['git','apply',str(P/'patches/linux/0030-gxlx2-runtime-sr-capability-guard.patch')],cwd=r,check=True)
 subprocess.run(['git','apply','--include='+F,str(P/'patches/linux/0031-gxlx2-pps-csc-transition-evidence.patch')],cwd=r,check=True)
 old=function(original).replace('int vpp_set_super_scaler_regs(','int baseline(');new=function(f.read_text())
 regs=sorted(set(re.findall(r'\b(?:VPP|SRSHARP)[A-Z0-9_]*\b',old+new)))
 fields=sorted(set(re.findall(r'\bsr->([a-z0-9_]+)',old+new)))
 c=r'''
#include <assert.h>
#include <stdbool.h>
#include <string.h>
typedef unsigned u32;
struct op{unsigned kind,reg,val,start,len;};
static struct op calls[256],expected[256];static unsigned count,cpu,seed;
static unsigned super_scaler,sr0_sr1_refresh,sharpness1_sr2_ctrl_32d7,sharpness1_sr2_ctrl_3280;
static void record(unsigned k,unsigned r,unsigned v,unsigned s,unsigned n){assert(count<256);calls[count++]=(struct op){k,r,v,s,n};}
static unsigned rd(unsigned r){record(0,r,0,0,0);return (r^seed)&63;}
#define VSYNC_RD_MPEG_REG(r) rd(r)
#define VSYNC_WR_MPEG_REG(r,v) record(1,r,v,0,32)
#define VSYNC_WR_MPEG_REG_BITS(r,v,s,n) record(2,r,v,s,n)
#define WRITE_VCBUS_REG_BITS(r,v,s,n) record(3,r,v,s,n)
#define MESON_CPU_MAJOR_ID_GXTVBB 0x20
#define MESON_CPU_MAJOR_ID_G12A 0x28
#define MESON_CPU_MAJOR_ID_TXHD 0x27
#define SUPER_CORE0_SUPPORT 1
#define SUPER_CORE1_SUPPORT 2
#define ONLY_CORE0 1
#define NEW_CORE0_CORE1 2
#define CORE0_PPS_CORE1 0
#define PPS_CORE0_CORE1 1
#define PPS_CORE0_POSTBLEND_CORE1 2
#define CORE0_CORE1_PPS 3
#define CORE1_BEFORE_PPS 4
#define CORE1_AFTER_PPS 5
#define CORE0_BEFORE_PPS 6
static void e900_note_pps(unsigned support,unsigned refresh){(void)support;(void)refresh;}
static unsigned get_cpu_type(void){return cpu;}
static bool cpu_after_eq(unsigned n){return cpu>=n;}
static bool is_meson_gxlx2_cpu(void){return cpu==0x2a;}
static bool is_meson_txlx_cpu(void){return cpu==0x26;}
static bool is_meson_txhd_cpu(void){return cpu==0x27;}
static bool is_meson_gxtvbb_cpu(void){return cpu==0x20;}
'''
 c+='struct sr_info_s{'+''.join('unsigned '+name+';' for name in fields)+'};\nstatic struct sr_info_s sr_info;\n'
 c+=''.join('#define '+name+' '+hex(0x1000+4*i)+'\n' for i,name in enumerate(regs))
 c+=old+new+r'''
static bool absent(unsigned r,unsigned cap){
 return (!(cap&1)&&(r==VPP_SRSHARP0_CTRL||r==SRSHARP0_SHARP_SR2_CTRL+sr_info.sr_reg_offt||r==SRSHARP0_SHARP_HVSIZE+sr_info.sr_reg_offt)) ||
 (!(cap&2)&&(r==VPP_SRSHARP1_CTRL||r==SRSHARP1_SHARP_SR2_CTRL+sr_info.sr_reg_offt2||r==SRSHARP1_SHARP_HVSIZE+sr_info.sr_reg_offt2));
}
static void caches(void){sharpness1_sr2_ctrl_32d7=17;sharpness1_sr2_ctrl_3280=23;count=0;}
int main(void){
 unsigned cpus[]={0x20,0x21,0x23,0x26,0x27,0x28,0x29,0x2a,0x2b,0x2e};
 unsigned widths[]={640,1920,4096};unsigned cidx,cap,refresh,enable,path,w,s,i,n,k;bool ve,out;
 for(cidx=0;cidx<10;cidx++)for(cap=0;cap<4;cap++)for(refresh=0;refresh<2;refresh++)for(enable=0;enable<2;enable++)for(path=0;path<7;path++)for(w=0;w<3;w++)for(s=0;s<2;s++){
  cpu=cpus[cidx];seed=s?63:0;super_scaler=enable;sr0_sr1_refresh=refresh;
  memset(&sr_info,0,sizeof(sr_info));sr_info.sr_support=cap;sr_info.sr_reg_offt=cpu>=0x28?0xc00:0;sr_info.sr_reg_offt2=cpu>=0x2e?0xc80:0;
  sr_info.core_support=NEW_CORE0_CORE1;sr_info.core0_v_disable_width_max=2048;sr_info.core0_v_enable_width_max=1024;
  caches();baseline(path,0,widths[w],720,1,1,0,1920,1080,1,1,1920,1080);n=count;memcpy(expected,calls,n*sizeof(*calls));
  caches();vpp_set_super_scaler_regs(path,0,widths[w],720,1,1,0,1920,1080,1,1,1920,1080);
  k=0;for(i=0;i<n;i++){if(cpu==0x2a&&absent(expected[i].reg,cap))continue;assert(k<count&&memcmp(&expected[i],&calls[k],sizeof(struct op))==0);k++;}assert(k==count);
  if(cpu==0x2a){ve=out=false;for(i=0;i<count;i++){assert(!absent(calls[i].reg,cap));ve|=calls[i].reg==VPP_VE_H_V_SIZE;out|=calls[i].reg==VPP_OUT_H_V_SIZE;}assert(ve&&out);}
 }
 return 0;
}
'''
 (r/'test.c').write_text(c)
 for std in ['gnu89','gnu99']:
  subprocess.run([shutil.which('clang') or 'cc','-std='+std,'-Wall','-Wextra','-Wno-unused-parameter','-Werror',str(r/'test.c'),'-o',str(r/'test')],check=True);subprocess.run([str(r/'test')],check=True)
print('PASS: real scaler I/O matches upstream except unsupported GXLX2 SR accesses; 10 CPUs x4 masks x refresh/off/path/size cases; common sizing preserved; ARM/playback pending')
