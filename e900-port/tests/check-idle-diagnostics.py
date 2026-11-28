#!/usr/bin/env python3
"""Count idle diagnostic dispatch and compare active logs; no device benchmark."""
import json,os,re,shutil,subprocess,tempfile
from pathlib import Path
P=Path(__file__).resolve().parents[1]
A=Path(os.environ.get('E900_AUDIT_ROOT',P.parent/'coreelec-audit'))
D='include/linux/amlogic/media/registers/'
common=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;
#define noinline __attribute__((noinline))
#define READ_ONCE(x) (*(volatile __typeof__(x) *)&(x))
#define WRITE_ONCE(x,v) ((x)=(v))
#define IS_ENABLED(x) 0
#define IS_REACHABLE(x) 0
#define ATOMIC_INIT(x) {x}
typedef struct {unsigned v;} atomic_t;
static unsigned atomic_inc_return(atomic_t *v){return ++v->v;}
static unsigned cpu=0x2a,queries,logs;
static noinline bool is_meson_gxlx2_cpu(void){queries++;return cpu==0x2a;}
struct kernel_param {void *arg;};
struct kernel_param_ops {int (*set)(const char*,const struct kernel_param*);int (*get)(char*,const struct kernel_param*);};
static int kstrtouint(const char *s,unsigned base,unsigned *v){*v=strtoul(s,0,base);return 0;}
static int param_get_uint(char *b,const struct kernel_param *p){return sprintf(b,"%u",*(unsigned*)p->arg);}
#define module_param_cb(...)
#define MODULE_PARM_DESC(...)
static unsigned cmpxchg(unsigned *p,unsigned old,unsigned n){unsigned seen=*p;if(seen==old)*p=n;return seen;}
static void pr_info(const char *fmt,...){
 char b[2048],*caller;va_list a;va_start(a,fmt);vsnprintf(b,sizeof b,fmt,a);va_end(a);
 caller=strstr(b," caller=");if(caller)*caller=0;puts(b);logs++;
}
'''
main=r'''
E900_DEBUG_CHANNEL("test")
E900_GEN3_RMW_CHANNEL("test")
/* Prevent caller folding while allowing the production wrapper to inline. */
void gen3_probe(unsigned reg){e900_gen3_rmw(reg,1,2,0,32,3,4,5,6,(void*)0x123);}
int main(void){
 unsigned i,id;unsigned idle;
 gxlx2_debug_events=gxlx2_gen3_rmw_events=0;
 for(i=0;i<200000;i++){
  gen3_probe(0x1aa7);e900_debug_event("idle",1,2,3,4);
 }
 idle=queries;assert(logs==0);
#ifdef EXPECT_FAST
 assert(idle==0);
#else
 assert(idle==400000);
#endif
 /* Compare the formatted active messages and budgets for all CPU IDs. */
 for(id=0;id<128;id++){
  unsigned old_logs=logs;
  cpu=id;gxlx2_debug_events=gxlx2_gen3_rmw_events=2;
  gen3_probe(0x1d00);assert(gxlx2_gen3_rmw_events==2);
  for(i=0;i<3;i++){
   gen3_probe(0x1aa7);e900_debug_event("active",1,2,3,4);
  }
  assert(logs-old_logs==(id==0x2a?4u:0u));
  assert(gxlx2_gen3_rmw_events==(id==0x2a?0u:2u));
  assert(gxlx2_debug_events==(id==0x2a?0u:2u));
 }
 fprintf(stderr,"idle CPU lookups=%u\n",idle);
 return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='e900-idle-perf-') as td:
 r=Path(td)
 for row in json.loads((P/'tests/source-fixtures.json').read_text()):
  if row['repo']=='CoreELEC/linux-amlogic':
   f=r/row['path'];f.parent.mkdir(parents=True,exist_ok=True)
   shutil.copyfile(A/'sources'/row['path'].replace('/','__'),f)
 baseline={}
 for p in sorted((P/'patches/linux').glob('*.patch')):
  if p.name.startswith('0046-'):
   baseline={name:(r/D/name).read_text() for name in ('e900_debug.h','e900_gen3_debug.h')}
   playback_before=(r/'drivers/amlogic/media/common/rdma/e900_playback_trace.h').read_text()
   submit_before=(r/'drivers/amlogic/media/common/rdma/e900_submit_trace.h').read_text()
  subprocess.run(['git','apply',str(p)],cwd=r,check=True)
 assert baseline
 outputs=[]
 for label in ('baseline','fast'):
  headers=baseline if label=='baseline' else {name:(r/D/name).read_text() for name in baseline}
  macro='\n'.join('\n'.join(x for x in h.splitlines() if not x.startswith('#include')) for h in headers.values())
  c=r/(label+'.c');c.write_text(common+'\n'+macro+'\n'+main)
  exe=r/label
  subprocess.run([shutil.which('clang') or 'cc','-O2','-std=gnu99','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-const-variable',*(['-DEXPECT_FAST'] if label=='fast' else []),str(c),'-o',str(exe)],check=True)
  result=subprocess.run([str(exe)],check=True,capture_output=True,text=True)
  outputs.append(result.stdout);print(label+': '+result.stderr.strip())
  if label=='fast':
   asm=r/'fast.s'
   subprocess.run([shutil.which('clang') or 'cc','-O2','-S','-DEXPECT_FAST',str(c),'-o',str(asm)],check=True)
   assert not re.search(r'^_?e900_gen3_rmw:',asm.read_text(),re.M),'GEN3 filter failed to inline at O2'
 assert outputs[0]==outputs[1],'active log payload/budget semantics changed'
 # The recorder changes must be ONLY short-circuit order, no row, lock,
 # lifetime, overflow, phase, batch, IRQ or MMIO policy changes.
 for name,old,status in [('e900_playback_trace.h',playback_before,'e900_playback_status'),('e900_submit_trace.h',submit_before,'e900_submit_status')]:
  new=(r/'drivers/amlogic/media/common/rdma'/name).read_text()
  restored=new.replace('READ_ONCE('+status+') != 1 || !is_meson_gxlx2_cpu()', '!is_meson_gxlx2_cpu() || READ_ONCE('+status+') != 1')
  restored=restored.replace('return READ_ONCE(e900_playback_status) == 1 &&\n\t\tis_meson_gxlx2_cpu();', 'return is_meson_gxlx2_cpu() &&\n\t\tREAD_ONCE(e900_playback_status) == 1;')
  assert restored==old,name
print('PASS: 200000 idle GEN3+debug calls remove 400000 CPU lookups in host harness; GEN3 filter inlined at O2; active logs/budgets unchanged for CPU IDs 0..127')
print('LIMIT: operation-count/source proof only; no ARM speed, frame-rate or CPU-utilization improvement measured')
