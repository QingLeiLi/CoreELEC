#!/usr/bin/env python3
"""Run actual video config and shared watchdog with simulated healthy OSD IRQs."""
from pathlib import Path
import json,os,re,subprocess,shutil,tempfile
P=Path(__file__).resolve().parents[1];A=Path(os.environ.get('E900_AUDIT_ROOT',P.parent/'coreelec-audit'))
def fn(s,name):
 m=re.search(r'^(?:static )?(?:void|int|bool) '+name+r'\([^;]*?\)\s*\{',s,re.M);assert m,name
 a=s.index('{',m.start());b=a+1;n=1
 while n:n+=(s[b]=='{')-(s[b]=='}');b+=1
 return s[m.start():b]+'\n'
with tempfile.TemporaryDirectory(prefix='e900-rdma-stall-') as td:
 r=Path(td)
 for row in json.loads((P/'tests/source-fixtures.json').read_text()):
  if row['repo']=='CoreELEC/linux-amlogic':
   f=r/row['path'];f.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(A/'sources'/row['path'].replace('/','__'),f)
 name='drivers/amlogic/media/common/rdma/rdma.c';old=(r/name).read_text()
 for p in sorted((P/'patches/linux').glob('*.patch')):subprocess.run(['git','apply',str(p)],cwd=r,check=True)
 new=(r/name).read_text();manager=(r/'drivers/amlogic/media/common/rdma/rdma_mgr.c').read_text()
 c=r'''
#include <assert.h>
#include <stdbool.h>
#include <string.h>
#define READ_ONCE(x) (x)
#define VSYNC_RDMA 0
#define LINE_N_INT_RDMA 1
#define RDMA_TRIGGER_VSYNC_INPUT 1
#define RDMA_TRIGGER_LINE_INPUT 64
#define RDMA_TRIGGER_MANUAL 256
#define RDMA_TRIGGER_DEBUG1 257
#define RDMA_TRIGGER_DEBUG2 258
#define pr_info(...) ((void)0)
static unsigned cpu,gxlx2_stall_frames,gxlx2_stall_count,gxlx2_stall_rearms;
static int cur_enable[2],enable[2],pre_enable_[2],vsync_rdma_handle[2],irq_count[2],vsync_cfg_count[2];
static bool first_config[2],rdma_done[2];static unsigned force_rdma_config[2];
static unsigned debug_flag;static int rdma_watchdog=20,rdma_watchdog_count,rdma_force_reset,rdma_reset_tigger_flag;
static unsigned resets,configs,clears,line_sets;static int config_result=1;
static unsigned calls[1024],ncall;
static void call(unsigned n){assert(ncall<1024);calls[ncall++]=n;}
static bool is_meson_gxlx2_cpu(void){return cpu==0x2a;}
static void e900_debug_event(const char*s,unsigned a,unsigned b,unsigned c,unsigned d){(void)s;(void)a;(void)b;(void)c;(void)d;}
static void rdma_reset(unsigned n){assert(n==1);resets++;call(1000);}
static void rdma_clear(int h){clears++;call(100+h);}
static int rdma_config(int h,int type){configs++;call(10000+h*1000+type);return config_result;}
static void set_rdma_trigger_line(void){line_sets++;call(200);}
'''+fn(manager,'rdma_watchdog_setting')+fn(old,'_vsync_rdma_config').replace('void _vsync_rdma_config(', 'void baseline(')+fn(new,'e900_rdma_stall_rearm')+fn(new,'_vsync_rdma_config')+r'''
static void reset(void){
 memset(cur_enable,0,sizeof(cur_enable));memset(enable,0,sizeof(enable));memset(pre_enable_,0,sizeof(pre_enable_));memset(first_config,0,sizeof(first_config));memset(rdma_done,0,sizeof(rdma_done));memset(force_rdma_config,0,sizeof(force_rdma_config));memset(irq_count,0,sizeof(irq_count));memset(vsync_cfg_count,0,sizeof(vsync_cfg_count));
 vsync_rdma_handle[0]=1;vsync_rdma_handle[1]=2;resets=configs=clears=line_sets=ncall=0;rdma_watchdog_count=0;rdma_force_reset=0;rdma_reset_tigger_flag=0;debug_flag=0;gxlx2_stall_frames=20;gxlx2_stall_count=gxlx2_stall_rearms=0;config_result=1;
}
static void setup(unsigned type,unsigned mode){first_config[type]=true;cur_enable[type]=pre_enable_[type]=enable[type]=mode;}
static void run(void(*f)(int),unsigned type,bool healthy){unsigned i;for(i=0;i<45;i++){rdma_watchdog_setting(0);rdma_done[type]=healthy;f(type);}}
int main(void){
 unsigned chips[]={0x21,0x26,0x28,0x29,0x2a,0x2b,0x2e};unsigned c,m,t,n,expected[1024];
 for(c=0;c<7;c++)for(m=0;m<7;m++)for(t=0;t<2;t++){
  cpu=chips[c];reset();setup(t,m);run(baseline,t,true);n=ncall;memcpy(expected,calls,n*sizeof(unsigned));
  reset();setup(t,m);run(_vsync_rdma_config,t,true);assert(ncall==n&&!memcmp(expected,calls,n*sizeof(unsigned))&&!gxlx2_stall_rearms);
  if(cpu!=0x2a||m!=1||t!=0){
   reset();setup(t,m);run(baseline,t,false);n=ncall;memcpy(expected,calls,n*sizeof(unsigned));
   reset();setup(t,m);run(_vsync_rdma_config,t,false);assert(ncall==n&&!memcmp(expected,calls,n*sizeof(unsigned))&&!gxlx2_stall_rearms);
  }
 }
 cpu=0x2a;reset();setup(0,1);run(baseline,0,false);assert(!configs&&!resets);/* healthy OSD hides stalled video forever */
 reset();setup(0,1);run(_vsync_rdma_config,0,false);assert(configs==2&&gxlx2_stall_rearms==2&&!resets&&vsync_cfg_count[0]==2);
 reset();setup(0,1);gxlx2_stall_frames=0;run(_vsync_rdma_config,0,false);assert(!configs&&!gxlx2_stall_rearms);
 reset();setup(0,1);for(c=0;c<19;c++){rdma_watchdog_setting(0);_vsync_rdma_config(0);}assert(gxlx2_stall_count==19&&!configs);
 rdma_done[0]=true;_vsync_rdma_config(0);assert(!gxlx2_stall_count&&!configs);
 reset();setup(0,1);gxlx2_stall_frames=3;for(c=0;c<3;c++){rdma_watchdog_setting(0);_vsync_rdma_config(0);}assert(configs==1&&gxlx2_stall_rearms==1);
 reset();setup(0,1);gxlx2_stall_count=19;force_rdma_config[0]=1;_vsync_rdma_config(0);assert(configs==1&&!gxlx2_stall_rearms&&!gxlx2_stall_count);
 return 0;
}
'''
 (r/'test.c').write_text(c)
 for std in ['gnu89','gnu99']:
  subprocess.run([shutil.which('clang') or 'cc','-std='+std,'-Wall','-Wextra','-Werror',str(r/'test.c'),'-o',str(r/'test')],check=True);subprocess.run([str(r/'test')],check=True)
print('PASS: actual shared-watchdog starvation reproduced; independent video retry, healthy IRQ/mode/other-CPU traces unchanged, no hardware reset; ARM pending')
