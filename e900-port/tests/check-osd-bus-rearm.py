#!/usr/bin/env python3
"""Compile real patched OSD start/stop/notifier paths with modeled MMIO/locks.

This verifies software intent/lifecycle, not real IRQ ordering or valid pixels.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

PORT=Path(__file__).resolve().parents[1]
AUDIT=Path(os.environ.get('E900_AUDIT_ROOT',PORT.parent/'coreelec-audit'))
RDMA='drivers/amlogic/media/osd/osd_rdma.c'
HW='drivers/amlogic/media/osd/osd_hw.c'

def function(src,name):
 m=re.search(r'^(?:static )?(?:inline )?(?:int|void) '+name+r'\([^;]*?\)\s*\{',src,re.M)
 assert m,name
 a=src.index('{',m.start());depth=1;b=a+1
 while depth:
  depth+=(src[b]=='{')-(src[b]=='}');b+=1
 return src[m.start():b]+'\n'

with tempfile.TemporaryDirectory(prefix='e900-osd-bus-') as tmp:
 root=Path(tmp);subprocess.run(['git','init','-q',str(root)],check=True)
 for row in json.loads((PORT/'tests/source-fixtures.json').read_text()):
  if row['repo']!='CoreELEC/linux-amlogic':continue
  data=(AUDIT/'sources'/row['path'].replace('/','__')).read_bytes()
  assert hashlib.sha256(data).hexdigest()==row['sha256']
  dest=root/row['path'];dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
 for patch in sorted((PORT/'patches/linux').glob('*.patch')):
  if patch.name.startswith('0048-'):before=(root/RDMA).read_text()
  subprocess.run(['git','apply',str(patch)],cwd=root,check=True)
 source=(root/RDMA).read_text();hw=(root/HW).read_text()
 a=source.index('#ifdef CONFIG_AMLOGIC_MEDIA_RDMA\n/* GXLX2\'s codec dispatcher')
 b=source.index('static int start_osd_rdma(char channel)',a)
 block=source[a:b]
 init=function(source,'osd_rdma_init');release=function(source,'osd_rdma_release')
 assert init.index('rdma_register(&osd_rdma_op')<init.index('codec_reg_register_ready_notifier')
 assert release.index('gxlx2_osd_bus_cancel')<release.index('dma_free_coherent')
 assert '.priority = -10' in block and 'module_param_named(gxlx2_osd_boot_rearm' in block
 prelude=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <errno.h>
typedef uint32_t u32;
typedef uint64_t dma_addr_t;
#define CONFIG_AMLOGIC_MEDIA_RDMA 1
#define module_param_named(a,b,c,d)
#define pr_info(...) ((void)0)
#define pr_warn(...) ((void)0)
#define NOTIFY_OK 1
#define IO_VC_BUS 5
#define PAGE_SIZE 4096U
#define RDMA_ACCESS_AUTO 0x1110
#define RDMA_TRIGGER_VSYNC_INPUT 1
#define RDMA_TRIGGER_LINE_INPUT 32
#define RDMA_AUTO_START_MASK 0x80000
#define START_ADDR 0x1106
#define END_ADDR 0x1107
struct notifier_block {int (*notifier_call)(struct notifier_block *,unsigned long,void *);int priority;};
static int cpu,ready,held,calls,clears,unregistered,reads,fail_config,skip_write;
static u32 auto_value,start_value,end_value;
static int rdma_lock;
static u32 rdma_enable,item_count,table_paddr,rdma_irq_count;
static void *rdma_table;
static dma_addr_t osd_rdma_table_phy;
static bool osd_rdma_init_flag;
static int osd_rdma_handle,osd_reset_rdma_handle;
static struct {int line_n_rdma;} osd_hw;
#define spin_lock_irqsave(lock,flags) do { (void)(lock);(flags)=0;assert(!held);held=1; } while(0)
#define spin_unlock_irqrestore(lock,flags) do { (void)(lock);(void)(flags);assert(held);held=0; } while(0)
static bool is_meson_gxlx2_cpu(void) {return cpu==0x2a;}
static bool codec_reg_bus_ready(u32 bus) {assert(bus==IO_VC_BUS);return ready;}
static void codec_reg_unregister_ready_notifier(struct notifier_block *nb) {assert(nb);assert(!held);unregistered++;}
static u32 osd_reg_read(u32 reg) {
 assert(held);reads++;
 if(reg==START_ADDR)return start_value;
 if(reg==END_ADDR)return end_value;
 assert(reg==RDMA_ACCESS_AUTO);return auto_value;
}
static int rdma_config(int handle,int trigger) {
 assert(handle==3);assert(trigger==(RDMA_TRIGGER_VSYNC_INPUT|RDMA_AUTO_START_MASK));calls++;
 if(fail_config)return -1;
 if(ready&&!skip_write)auto_value=(auto_value&~0xff000088U)|0x01000080;
 return 1;
}
static int rdma_clear(int handle) {assert(handle==3||handle==2);clears++;auto_value&=~0xff000000U;return 0;}
'''
 # Original functions form a non-GXLX2/disabled reference using the same stubs.
 functions=function(source,'start_osd_rdma')+function(source,'stop_rdma')
 baseline=function(before,'start_osd_rdma').replace('start_osd_rdma','baseline_start')+function(before,'stop_rdma').replace('stop_rdma','baseline_stop')
 main=r'''
static void reset(void) {
 cpu=0x2a;ready=0;held=0;calls=0;clears=0;reads=0;unregistered=0;fail_config=0;skip_write=0;
 auto_value=0x120;start_value=table_paddr=0x34e10000;end_value=table_paddr+15;
 osd_rdma_table_phy=table_paddr;rdma_enable=1;rdma_irq_count=0;item_count=2;
 osd_rdma_init_flag=true;rdma_table=&auto_value;osd_rdma_handle=3;osd_reset_rdma_handle=2;
 gxlx2_osd_boot_rearm=true;gxlx2_osd_start_pending=false;gxlx2_osd_releasing=false;
 gxlx2_osd_bus_subscribed=true;gxlx2_osd_rearm_status=0;
}
static void publish(void) {ready=1;gxlx2_osd_bus_ready(NULL,0,NULL);assert(!held);}
int main(void) {
 int i,expected;
 for(i=0;i<4;i++) {
  reset();cpu=(int[]){0x1f,0x21,0x28,0x2b}[i];baseline_start(3);expected=calls;
  calls=0;start_osd_rdma(3);assert(calls==expected&&!gxlx2_osd_start_pending);
  clears=0;baseline_stop(3);expected=clears;clears=0;stop_rdma(3);assert(clears==expected);
 }
 reset();gxlx2_osd_boot_rearm=false;start_osd_rdma(3);assert(calls==1&&!gxlx2_osd_start_pending);
 reset();start_osd_rdma(3);assert(calls==0&&reads==0&&gxlx2_osd_start_pending&&gxlx2_osd_rearm_status==1);
 gxlx2_osd_bus_ready(NULL,0,NULL);assert(calls==0&&gxlx2_osd_start_pending);
 publish();assert(calls==1&&gxlx2_osd_rearm_status==2&&!gxlx2_osd_start_pending);
 assert(auto_value==0x010001a0&&start_value==table_paddr&&end_value==table_paddr+15&&item_count==2);
 publish();assert(calls==1); /* duplicate delivery must not reconfigure */
 reset();ready=1;gxlx2_osd_bus_ready(NULL,0,NULL);start_osd_rdma(3);assert(calls==1&&!gxlx2_osd_start_pending);
 reset();start_osd_rdma(3);stop_rdma(3);publish();assert(!calls&&clears==2&&!gxlx2_osd_start_pending);
 reset();start_osd_rdma(3);gxlx2_osd_bus_cancel();assert(unregistered==1&&gxlx2_osd_releasing);
 rdma_table=NULL;publish();assert(!calls&&!reads); /* table may now be freed */
 assert(gxlx2_osd_start(3)==-ENODEV&&!calls);
 reset();start_osd_rdma(3);auto_value=0x014001e0;publish();assert(!calls&&gxlx2_osd_rearm_status==3);
 reset();start_osd_rdma(3);auto_value|=0x00400040;publish();assert(auto_value==0x014001e0);
 reset();start_osd_rdma(3);end_value=start_value-1;publish();assert(calls==1); /* native empty table */
 for(i=0;i<7;i++) {
  reset();start_osd_rdma(3);
  switch(i) {
   case 0:osd_rdma_handle=4;break;
   case 1:rdma_table=NULL;break;
   case 2:osd_rdma_table_phy+=0x100000000ULL;break;
   case 3:start_value+=8;break;
   case 4:end_value=start_value+PAGE_SIZE+7;break;
   case 5:end_value=start_value+8;break;
   case 6:table_paddr=0;break;
  }
  publish();assert(!calls&&gxlx2_osd_rearm_status<0&&!gxlx2_osd_start_pending);
 }
 reset();start_osd_rdma(3);rdma_enable=0;publish();assert(!calls);
 reset();start_osd_rdma(3);osd_rdma_init_flag=false;publish();assert(!calls&&!reads);
 reset();start_osd_rdma(3);fail_config=1;publish();assert(calls==1&&gxlx2_osd_rearm_status==-EIO);
 reset();start_osd_rdma(3);skip_write=1;publish();assert(calls==1&&gxlx2_osd_rearm_status==-EIO);
 return 0;
}
'''
 test=root/'test.c';test.write_text(prelude+block+functions+baseline+main)
 compiler=shutil.which('clang') or 'cc'
 for standard in ['gnu89','gnu99']:
  subprocess.run([compiler,'-std='+standard,'-Wall','-Wextra','-Werror',str(test),'-o',str(root/'test')],check=True)
  subprocess.run([str(root/'test')],check=True)
 print('PASS: real OSD start/stop/notifier preserves other CPUs, defers/replays once, cancels before release and validates live DMA/CH3/readback')
 # Timeout diagnostics must leave normal waits/signal handling unchanged.
 wait=function(hw,'osd_wait_vsync_hw_viu1')
 assert 'msecs_to_jiffies(1000)' in wait and 'unlikely(waited == 0) && is_meson_gxlx2_cpu()' in wait
 assert 'osd_rdma_vpp0_done_wq, vsync_hit[VIU1], timeout' in wait
 print('PASS: original OSD wait condition/timeout retained; diagnostics limited to timeout path')
 print('PENDING: full ARM link, real notifier/IRQ concurrency, cold/warm boot timing and visible menu/playback')
