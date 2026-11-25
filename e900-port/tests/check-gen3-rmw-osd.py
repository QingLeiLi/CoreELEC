#!/usr/bin/env python3
"""Execute actual RMW code and legacy OSD decision with kernel stubs."""
from pathlib import Path
import json,os,re,shutil,subprocess,tempfile
P=Path(__file__).resolve().parents[1]
A=Path(os.environ.get('E900_AUDIT_ROOT',P.parent/'coreelec-audit'))
def function(s,name):
 m=re.search(r'^(?:static )?(?:bool|int|void) '+name+r'\([^;]*?\)\s*\{',s,re.M);assert m,name
 a=s.index('{',m.start());b=a+1;n=1
 while n:n+=(s[b]=='{')-(s[b]=='}');b+=1
 return s[m.start():b]
with tempfile.TemporaryDirectory(prefix='e900-rmw-osd-') as d:
 r=Path(d)
 for row in json.loads((P/'tests/source-fixtures.json').read_text()):
  if row['repo']!='CoreELEC/linux-amlogic':continue
  p=r/row['path'];p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(A/'sources'/row['path'].replace('/','__'),p)
 for patch in sorted((P/'patches/linux').glob('*.patch')):subprocess.run(['git','apply',str(patch)],cwd=r,check=True)
 rd=(r/'drivers/amlogic/media/common/rdma/rdma.c').read_text();mgr=(r/'drivers/amlogic/media/common/rdma/rdma_mgr.c').read_text();osd=(r/'drivers/amlogic/media/osd/osd_hw.c').read_text()
 header=(r/'include/linux/amlogic/media/registers/e900_gen3_debug.h').read_text();header='\n'.join(x for x in header.splitlines() if not x.startswith('#include'))
 # Exercise the exact legacy branch preceding the separate AFBC handling.
 a=osd.index('\tif (osd_hw.osd_meson_dev.osd_ver <= OSD_NORMAL)',osd.index('static void osd_update_enable'))
 b=osd.index('\n\tif (osd_hw.osd_meson_dev.afbc_type == MESON_AFBC)',a)
 branch=osd[a:b]
 common=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
typedef unsigned u32;
#define noinline __attribute__((noinline))
#define READ_ONCE(x) (x)
#define module_param_cb(...)
#define MODULE_PARM_DESC(...)
static unsigned cpu=0x2a,logs,reads,writes,hw=0x3033,last_value;
static char last_log[2048];
static bool is_meson_gxlx2_cpu(void){return cpu==0x2a;}
static unsigned cmpxchg(unsigned*p,unsigned o,unsigned n){unsigned seen=*p;if(seen==o)*p=n;return seen;}
static void pr_info(const char*f,...){va_list a;va_start(a,f);vsnprintf(last_log,sizeof last_log,f,a);va_end(a);logs++;}
#define Rd(adr) (reads++,hw)
#define Wr(adr,val) (writes++,last_value=(val))
#define VSYNC_RDMA 0
static int cur_enable[1],vsync_rdma_handle[1]={1};static unsigned debug_flag[1];
static unsigned queued_val,queued_start,queued_len;
static void rdma_write_reg(int h,u32 a,u32 v){(void)h;(void)a;queued_val=v;}
static void rdma_write_reg_bits(int h,u32 a,u32 v,u32 s,u32 l){(void)h;(void)a;queued_val=v;queued_start=s;queued_len=l;}
#define OSD1 0
#define OSD2 1
#define OSD_NORMAL 1
#define MESON_AFBC 1
#define MALI_AFBC 2
#define ENABLE 1
#define VPP_OSD1_POSTBLEND (1u<<12)
#define VPP_OSD2_POSTBLEND (1u<<13)
#define VPP_POSTBLEND_EN (1u<<7)
#define VPP_MISC 3
#define __MESON_CPU_MAJOR_ID_G12B 0x29
static bool gxlx2_osd_blender_only;
static struct {struct {unsigned osd_ver,afbc_type,cpu_id;} osd_meson_dev;unsigned enable[2];} osd_hw;
static struct regs {unsigned osd_ctrl_stat;} regs;
static unsigned osd_vpp_misc,ctrl,blend,notify;
static void set(unsigned reg,unsigned mask){if(reg==VPP_MISC)blend|=mask;else ctrl|=mask;}
static void clear(unsigned reg,unsigned mask){if(reg==VPP_MISC)blend&=~mask;else ctrl&=~mask;}
#define VSYNCOSD_SET_MPEG_REG_MASK set
#define VSYNCOSD_CLR_MPEG_REG_MASK clear
static void notify_to_amvideo(void){notify++;}
static void e900_debug_event(const char*e,u32 a,u32 b,u32 c,u32 d){(void)e;(void)a;(void)b;(void)c;(void)d;}
'''
 c=common+'\n'+header+'\nE900_GEN3_RMW_CHANNEL("rdma")\n'+function(rd,'VSYNC_WR_MPEG_REG_BITS')+'\n'+function(rd,'VSYNC_WR_MPEG_REG')+'\n'+function(osd,'e900_keep_osd_fetch')+'\nstatic void osd_branch(unsigned index){unsigned temp_val=0;struct regs*osd_reg=&regs;'+branch+'}\n'+r'''
int main(void){
 for(cpu=0;cpu<0x40;cpu++)for(unsigned armed=0;armed<2;armed++)for(unsigned addr=0;addr<2;addr++)for(unsigned start=0;start<16;start++){
  gxlx2_gen3_rmw_events=armed?3:0;unsigned prior=logs;reads=writes=0;cur_enable[0]=0;hw=0x3033;
  VSYNC_WR_MPEG_REG_BITS(addr?0x1aa7:0x3216,0,start,1);
  assert(reads==1&&writes==1&&last_value==(hw&~(1u<<start)));
  assert(logs-prior==((cpu==0x2a&&armed&&addr)?1u:0u));
 }
 cpu=0x2a;gxlx2_gen3_rmw_events=1;cur_enable[0]=0;reads=writes=0;
 VSYNC_WR_MPEG_REG(0x1aa7,0x33);assert(reads==0&&writes==1&&last_value==0x33&&strstr(last_log,"source=4"));
 cpu=0x2a;gxlx2_gen3_rmw_events=1;cur_enable[0]=1;reads=writes=0;
 VSYNC_WR_MPEG_REG_BITS(0x1aa7,0,12,2);assert(!reads&&!writes&&queued_start==12&&queued_len==2&&queued_val==0);assert(strstr(last_log,"source=-1"));
 cur_enable[0]=0;gxlx2_gen3_rmw_events=2;hw=0x3033;
 VSYNC_WR_MPEG_REG_BITS(0x1aa7,0,12,2);assert(last_value==0x33);
 /* Emulate hardware returning high bits: next ordinary bit0 RMW carries them. */
 VSYNC_WR_MPEG_REG_BITS(0x1aa7,1,0,1);assert(last_value==0x3033);
 for(cpu=0;cpu<0x40;cpu++)for(unsigned option=0;option<2;option++)for(unsigned idx=0;idx<2;idx++)for(unsigned ver=0;ver<4;ver++)for(unsigned afbc=0;afbc<3;afbc++){
  osd_hw.osd_meson_dev.osd_ver=ver;osd_hw.osd_meson_dev.afbc_type=afbc;osd_hw.osd_meson_dev.cpu_id=0x21;gxlx2_osd_blender_only=option;
  bool expected=cpu==0x2a&&option&&idx==0&&ver<=OSD_NORMAL&&afbc==0;
  assert(e900_keep_osd_fetch(idx)==expected);
  if(ver>OSD_NORMAL)continue;
  ctrl=1;blend=VPP_OSD1_POSTBLEND|VPP_OSD2_POSTBLEND;osd_vpp_misc=blend;osd_hw.enable[idx]=0;
  osd_branch(idx);assert(!(blend&(idx?VPP_OSD2_POSTBLEND:VPP_OSD1_POSTBLEND)));assert(ctrl==(expected?1u:0u));
  osd_hw.enable[idx]=1;osd_branch(idx);assert(ctrl==1&&(blend&(idx?VPP_OSD2_POSTBLEND:VPP_OSD1_POSTBLEND)));
 }
 return 0;
}
'''
 (r/'test.c').write_text(c);subprocess.run([shutil.which('clang') or 'cc','-std=gnu99','-Wall','-Wextra','-Werror',str(r/'test.c'),'-o',str(r/'test')],check=True);subprocess.run([str(r/'test')],check=True)
 # Compile/execute the whole real queued RMW function with each base source.
 mgr_common=common[:common.index('#define Rd(adr)')]+r'''
#define READ_VCBUS_REG(adr) (reads++,hw)
static int rdma_trace_num;static unsigned rdma_trace_reg[1],debug_flag;
struct rdma_instance_s {unsigned rdma_table_size;int rdma_item_count,rdma_write_count;u32 reg_buf[8],*rdma_table_addr;};
struct rdma_device_info {struct rdma_instance_s rdma_ins[2];};
static struct rdma_device_info rdma_info;
static bool conflict;static u32 conflict_value;
static bool rdma_check_conflict(int h,u32 a,u32*v){(void)h;(void)a;if(conflict)*v=conflict_value;return conflict;}
static void rdma_update_conflict(u32 a,u32 v){(void)a;conflict_value=v;}
static void rdma_write_reg(int h,u32 a,u32 v){(void)h;(void)a;writes++;last_value=v;}
'''
 mc=mgr_common+'\n'+header+'\nE900_GEN3_RMW_CHANNEL("rdma_mgr")\n'+function(mgr,'rdma_write_reg_bits')+r'''
int main(void){
 u32 table[8]={0};struct rdma_instance_s *ins=&rdma_info.rdma_ins[1];ins->rdma_table_size=4096;ins->rdma_table_addr=table;
 for(unsigned src=0;src<4;src++){
  ins->rdma_item_count=0;ins->rdma_write_count=0;conflict=false;hw=0x33;reads=writes=0;gxlx2_gen3_rmw_events=1;
  if(src==1){ins->rdma_item_count=1;ins->reg_buf[0]=0x1aa7;ins->reg_buf[1]=0x3033;}
  if(src==2){ins->rdma_write_count=1;table[0]=0x1aa7;table[1]=0x3033;}
  if(src==3){conflict=true;conflict_value=0x3033;}
  rdma_write_reg_bits(1,0x1aa7,1,0,1);assert(reads==1);
  char expected[32];snprintf(expected,sizeof expected,"source=%u",src);assert(strstr(last_log,expected));
  unsigned v=src?0x3033:0x33;if(src==1)assert(ins->reg_buf[1]==v);else assert(writes==1&&last_value==v);
 }
 return 0;
}
'''
 (r/'manager.c').write_text(mc);subprocess.run([shutil.which('clang') or 'cc','-std=gnu99','-Wall','-Wextra','-Werror',str(r/'manager.c'),'-o',str(r/'manager')],check=True);subprocess.run([str(r/'manager')],check=True)
 reg=(r/'drivers/amlogic/media/common/arch/registers/register_ops.c').read_text()
 rc=common[:common.index('#define Rd(adr)')]+r'''
#define IO_VC_BUS 2
static u32 codec_reg_read(u32 bus,unsigned reg){(void)bus;(void)reg;reads++;return hw;}
static void codec_reg_write(u32 bus,unsigned reg,u32 value){(void)bus;(void)reg;writes++;last_value=value;}
'''+'\n'+header+'\nE900_GEN3_RMW_CHANNEL("registers")\n'+function(reg,'codec_reg_write_bits')+r'''
int main(void){
 for(unsigned bus=0;bus<4;bus++){
  reads=writes=0;gxlx2_gen3_rmw_events=1;unsigned prior=logs;
  codec_reg_write_bits(bus,0x1aa7,0,12,2);
  assert(reads==1&&writes==1&&last_value==0x33);assert(logs-prior==(bus==IO_VC_BUS?1u:0u));
 }
 return 0;
}
'''
 (r/'registers.c').write_text(rc);subprocess.run([shutil.which('clang') or 'cc','-std=gnu99','-Wall','-Wextra','-Werror',str(r/'registers.c'),'-o',str(r/'registers')],check=True);subprocess.run([str(r/'registers')],check=True)
 # Manager logging captures existing read: no new hardware reads introduced.
 f=function(mgr,'rdma_write_reg_bits');assert f.count('READ_VCBUS_REG(adr)')==1
 assert f.index('e900_hardware = read_val')<f.index('rdma_check_conflict(')<f.index('e900_gen3_rmw(')
 assert 'e900_hardware, read_val, write_val, read_from' in f
print('PASS: actual direct GEN3 RMW preserves reads/writes, gated independent logs, queued intent; actual legacy OSD branch disables blend only for opted-in GXLX2 OSD1/no-AFBC and restores on enable. Full ARM/hardware pending.')

# Exercise the real operator runner: no VDIN in control-only mode, stopped
# snapshot, N/Y isolation and restoration after collection failure.
import importlib.util,io,contextlib,sys
from unittest import mock
spec=importlib.util.spec_from_file_location('display_runner',P/'scripts/e900-calibrate-loopback.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
with tempfile.TemporaryDirectory(prefix='e900-runner-') as d:
 root=Path(d);sample=root/'sample.mp4';sample.write_bytes(b'fixture')
 mapping={}
 for name,value in {
  '/sys/module/amvideo/parameters/gxlx2_hw_init_status':'2',
  '/sys/class/vdec/vdec_status':'No vdec.',
  '/proc/sys/kernel/random/boot_id':'test-boot',
  '/sys/module/amvideo/parameters/gxlx2_gen3_clear_high':'N',
  '/sys/module/fb/parameters/gxlx2_osd_blender_only':'N',
  '/sys/class/graphics/fb0/blank':'0',
  '/sys/module/rdma/parameters/enable':'1,0',
  '/sys/module/amvideo/parameters/gxlx2_pixel_scan':'idle',
 }.items():
  p=root/name.lstrip('/');p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value);mapping[name]=p
 def paths(value):return mapping.get(str(value),Path(value))
 for candidate,fail,pixels in [(False,False,False),(True,False,False),(True,True,False),(False,False,True)]:
  commands=[]
  def command(argv,**kwargs):
   commands.append(argv);out=''
   assert not any('e900-start-capture.sh' in a for a in argv)
   if any('PlayMedia(' in a for a in argv):mapping['/sys/class/vdec/vdec_status'].write_text('ammvdec_h264')
   if '--action=Stop' in argv:mapping['/sys/class/vdec/vdec_status'].write_text('No vdec.')
   if 'snapshot' in argv:
    assert ('--pipeline-pixels' in argv)==(pixels and 'stopped_unobserved' not in argv)
    if fail:raise RuntimeError('injected snapshot failure')
    out=str(root/'snapshot')+'\n'
   return subprocess.CompletedProcess(argv,0,stdout=out,stderr='')
  args=['case','--control-only','--osd-cycle','--sample',str(sample),'--output',str(root/'output')]
  if candidate:args.append('--osd-blender-only')
  if pixels:args.append('--pipeline-pixels')
  with mock.patch.object(runner,'Path',side_effect=paths),mock.patch.object(runner.runpy,'run_path',return_value={'kodi_state':lambda:{'status':'ok'}}),mock.patch.object(runner.subprocess,'run',side_effect=command),mock.patch.object(runner.time,'sleep'),mock.patch.object(sys,'argv',args),contextlib.redirect_stdout(io.StringIO()):
   assert runner.main()==(1 if fail else 0)
  assert mapping['/sys/module/fb/parameters/gxlx2_osd_blender_only'].read_text().strip()=='N'
  assert mapping['/sys/class/graphics/fb0/blank'].read_text().strip()=='0'
  assert mapping['/sys/class/vdec/vdec_status'].read_text().strip()=='No vdec.'
  if not fail:assert any('stopped_unobserved' in c for c in commands)
  assert any('disarm' in c for c in commands)
print('PASS: real control-only baseline/candidate runner avoids VDIN and restores OSD/player/log state on success and failure')
