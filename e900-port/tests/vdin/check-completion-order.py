#!/usr/bin/env python3
"""Run real completion checks against a latched flag with read/ACK tracing."""
from pathlib import Path
import difflib,hashlib,json,os,re,shutil,subprocess,tempfile
PORT=Path(__file__).resolve().parents[2]
AUDIT=Path(os.environ.get('E900_AUDIT_ROOT',PORT.parent/'coreelec-audit'))
FILE='drivers/amlogic/media/vin/tvin/vdin/vdin_ctl.c'
original=(AUDIT/'sources'/FILE.replace('/','__')).read_text()
row=next(r for r in json.loads((PORT/'tests/source-fixtures.json').read_text()) if r['path']==FILE)
assert hashlib.sha256(original.encode()).hexdigest()==row['sha256']
def function(source):
 start=source.index('bool vdin_write_done_check',source.index('#else\nbool vdin_write_done_check'))
 end=source.index('\n}',start)+2
 return source[start:end]
with tempfile.TemporaryDirectory(prefix='e900-vdin-completion-') as d:
 root=Path(d);p=root/FILE;p.parent.mkdir(parents=True);p.write_text(original)
 subprocess.run(['git','apply',str(PORT/'patches/linux/0018-gxlx2-vdin-observe-before-ack.patch')],cwd=root,check=True)
 old=function(original);new=function(p.read_text())
 c=r'''
#include <assert.h>
#include <stdbool.h>
#include <string.h>
#define VDIN_WR_CTRL 0x1220
#define VDIN_COM_STATUS0 0x1205
#define VDIN_RO_WRMIF_STATUS 0x1258
#define DIRECT_DONE_STATUS_BIT 2
#define DIRECT_DONE_STATUS_WID 1
#define DIRECT_DONE_CLR_BIT 21
#define DIRECT_DONE_CLR_WID 1
#define WRITE_DONE_BIT 0
#define WRITE_DONE_WID 1
#define MESON_CPU_MAJOR_ID_TM2 0x2f
struct vdin_dev_s {unsigned wr_done_abnormal_cnt;};
struct event {unsigned write,offset,reg,value,bit,width;};
static struct event log_events[16];static unsigned count,cpu;static bool latched,modern;
static bool is_meson_gxlx2_cpu(void){return cpu==0x2a;}
static bool cpu_after_eq(unsigned id){return cpu>=id;}
static unsigned rd_bits(unsigned offset,unsigned reg,unsigned bit,unsigned width){
 log_events[count++]=(struct event){0,offset,reg,0,bit,width};
 assert(offset==0x80&&width==1);
 assert((reg==VDIN_COM_STATUS0&&bit==2)||(reg==VDIN_RO_WRMIF_STATUS&&bit==0));
 return reg==VDIN_COM_STATUS0?latched:modern;
}
static void wr_bits(unsigned offset,unsigned reg,unsigned value,unsigned bit,unsigned width){
 log_events[count++]=(struct event){1,offset,reg,value,bit,width};
 assert(offset==0x80&&reg==VDIN_WR_CTRL&&bit==21&&width==1);
 if(value)latched=false;
}
'''+old.replace('vdin_write_done_check','baseline')+'\n'+new+r'''
static void reset(bool ready,bool newer){count=0;latched=ready;modern=newer;memset(log_events,0,sizeof log_events);}
int main(void){
 for(cpu=0;cpu<0x40;cpu++)for(unsigned ready=0;ready<2;ready++)for(unsigned newer=0;newer<2;newer++){
  struct vdin_dev_s before={7},after={7};struct event expected[16];unsigned n;bool result;
  reset(ready,newer);result=baseline(0x80,&before);n=count;memcpy(expected,log_events,sizeof expected);
  reset(ready,newer);bool observed=vdin_write_done_check(0x80,&after);
  if(cpu==0x2a){
   assert(observed==(bool)ready);assert(after.wr_done_abnormal_cnt==7+!ready);
   assert(log_events[0].write==0&&log_events[0].reg==VDIN_COM_STATUS0);
   assert(count==(ready?3:1));
   if(ready){assert(log_events[1].write&&log_events[1].value==1);assert(log_events[2].write&&log_events[2].value==0);assert(!latched);}
  }else{assert(result==observed&&before.wr_done_abnormal_cnt==after.wr_done_abnormal_cnt&&n==count&&!memcmp(expected,log_events,sizeof expected));}
 }
 return 0;
}
'''
 (root/'test.c').write_text(c)
 subprocess.run([shutil.which('clang') or 'cc','-std=gnu99','-Wall','-Wextra','-Werror',str(root/'test.c'),'-o',str(root/'test')],check=True)
 subprocess.run([str(root/'test')],check=True)
print('PASS: real GXLX2 check observes latched completion before ACK and never succeeds without it; all other CPU/status call sequences match upstream')
