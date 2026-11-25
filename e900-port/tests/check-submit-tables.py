#!/usr/bin/env python3
"""Run real normal-trigger config + bounded trace; compare original MMIO calls."""
import json,os,re,shutil,subprocess,tempfile
from pathlib import Path
P=Path(__file__).resolve().parents[1];A=Path(os.environ.get('E900_AUDIT_ROOT',P.parent/'coreelec-audit'))
def fn(s,name):
 m=re.search(r'^(?:static )?(?:void|int) '+name+r'\([^;]*?\)\s*\{',s,re.M);assert m,name
 a=s.index('{',m.start());b=a+1;n=1
 while n:n+=(s[b]=='{')-(s[b]=='}');b+=1
 return s[m.start():b]
def struct(s,name):
 a=s.index('struct '+name+' {');return s[a:s.index('\n};',a)+3]
with tempfile.TemporaryDirectory(prefix='e900-submit-') as td:
 r=Path(td)
 for row in json.loads((P/'tests/source-fixtures.json').read_text()):
  if row['repo']=='CoreELEC/linux-amlogic':
   f=r/row['path'];f.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(A/'sources'/row['path'].replace('/','__'),f)
 path='drivers/amlogic/media/common/rdma/rdma_mgr.c';old=(r/path).read_text()
 for patch in sorted((P/'patches/linux').glob('*.patch')):subprocess.run(['git','apply',str(patch)],cwd=r,check=True)
 new=(r/path).read_text();header=(r/'drivers/amlogic/media/common/rdma/e900_submit_trace.h').read_text();header='\n'.join(l for l in header.splitlines() if not l.startswith('#include'))
 assert new.index('e900_submit_end(i, rdma_status, 2);')<new.index('ins->op->irq_cb(ins->op->arg);')
 assert new.index('e900_submit_table(handle, trigger_type,')>new.index('memcpy(ins->rdma_table_addr')
 assert not re.search(r'\b(?:READ|WRITE)_VCBUS|pr_info\(',header)
 c=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
typedef uint32_t u32;typedef uint64_t u64;typedef u64 dma_addr_t;
#define RDMA_NUM 8
#define MAX_CONFLICT 32
#define RDMA_AUTO_START_MASK 0x80000
#define RDMA_TRIGGER_MANUAL 0x100
#define RDMA_ACCESS_MAN 0x1113
#define READ_ONCE(x) (x)
#define PAGE_SIZE 4096
#define scnprintf snprintf
#define module_param_cb(...)
#define module_param_named(...)
#define DEFINE_SPINLOCK(n) int n
static unsigned depth,cpu,hw_calls,clocktick;
#define spin_lock_irqsave(l,f) do{(void)(l);(f)=0;depth++;}while(0)
#define spin_unlock_irqrestore(l,f) do{(void)(l);(void)(f);assert(depth);depth--;}while(0)
static u64 get_jiffies_64(void){return ++clocktick;}
static bool is_meson_gxlx2_cpu(void){return cpu==0x2a;}
struct kernel_param{void*arg;};
struct kernel_param_ops{int(*set)(const char*,const struct kernel_param*);int(*get)(char*,const struct kernel_param*);};
static int kstrtouint(const char*s,int b,unsigned*n){char*e;unsigned long v=strtoul(s,&e,b);if(e==s||*e||*s=='-'||v>0xfffffffful)return -EINVAL;*n=v;return 0;}
struct rdma_op_s {void(*irq_cb)(void*);void*arg;};
struct rdma_device_data_s{int trigger_mask_len;};
struct call{u32 r,v,s,l;};static struct call calls[10000];
static void wr(u32 r,u32 v,u32 s,u32 l){assert(hw_calls<10000);calls[hw_calls++]=(struct call){r,v,s,l};}
#define READ_VCBUS_REG(r) ((void)(r),0x13579u)
#define WRITE_VCBUS_REG(r,v) wr(r,v,0,32)
#define WRITE_VCBUS_REG_BITS(r,v,s,l) wr(r,v,s,l)
#define pr_info(...) ((void)0)
'''+''.join(struct(old,n)+'\n' for n in ['rdma_regadr_s','rdma_instance_s','rdma_conflict_regs_s','rdma_device_info'])+r'''
static struct rdma_device_info rdma_info;
static struct rdma_device_data_s rdma_meson_dev;
static unsigned debug_flag;static int rdma_lock;
'''+header+'\n'+fn(old,'rdma_config').replace('int rdma_config(', 'int baseline(')+'\n'+fn(new,'rdma_config')+'\n'+fn(new,'rdma_clear')+r'''
static u32 pending[1024],table[1024];static struct rdma_regadr_s regs;static struct rdma_op_s op;
static void reset(void){
 memset(&rdma_info,0,sizeof rdma_info);memset(&regs,0,sizeof regs);memset(pending,0,sizeof pending);memset(table,0,sizeof table);memset(e900_submit_pending,0,sizeof e900_submit_pending);
 rdma_info.rdma_ins[1].op=&op;rdma_info.rdma_ins[1].rdma_regadr=&regs;rdma_info.rdma_ins[0].rdma_regadr=&regs;
 rdma_info.rdma_ins[1].reg_buf=pending;rdma_info.rdma_ins[1].rdma_table_addr=table;rdma_info.rdma_ins[1].rdma_table_phy_addr=0x4000;
 rdma_meson_dev.trigger_mask_len=8;hw_calls=depth=clocktick=debug_flag=0;
 e900_submit_status=e900_submit_generation=e900_submit_count=e900_submit_overflow=e900_submit_page=e900_submit_batch=0;
}
static void prepare(void){unsigned i;for(i=0;i<8;i++){pending[i*2]=i==0?0x1d03:i==7?0x9999:0x1d04;pending[i*2+1]=i+100;}rdma_info.rdma_ins[1].rdma_item_count=8;}
int main(void){
 assert(e900_submit_ops.set==e900_submit_set&&e900_submit_ops.get==e900_submit_get&&e900_submit_data_ops.get==e900_submit_data);
 unsigned cpus[]={0x21,0x28,0x29,0x2a,0x2b,0x2e},triggers[]={0,1,64,256,257,258,0x80001},i,t,n;struct call expected[10000];int a,b;char buf[4096];
 for(i=0;i<6;i++)for(t=0;t<7;t++){
  cpu=cpus[i];reset();prepare();a=baseline(1,triggers[t]);n=hw_calls;memcpy(expected,calls,n*sizeof(*calls));
  reset();prepare();b=rdma_config(1,triggers[t]);assert(a==b&&hw_calls==n&&!memcmp(expected,calls,n*sizeof(*calls))&&!e900_submit_count);
  reset();prepare();e900_submit_status=1;b=rdma_config(1,triggers[t]);assert(a==b&&hw_calls==n&&!memcmp(expected,calls,n*sizeof(*calls)));
  if(cpu!=0x2a)assert(!e900_submit_count);
 }
 cpu=0x2a;reset();assert(!e900_submit_set("1",0));assert(e900_submit_set("1",0)==-EBUSY);assert(e900_submit_data(buf,0)==-EBUSY);
 prepare();rdma_config(1,1);assert(e900_submit_count==8&&e900_submit_rows[0].kind==0&&e900_submit_rows[0].item==8);
 for(i=1;i<8;i++){assert(e900_submit_rows[i].kind==1&&e900_submit_rows[i].item==i-1&&e900_submit_rows[i].value==i+99);}
 assert(e900_submit_pending[1]==1);e900_submit_end(1,0x1000000,2);assert(e900_submit_count==9&&e900_submit_rows[8].kind==2);e900_submit_end(1,0,2);assert(e900_submit_count==9);
 assert(!e900_submit_set("0",0));assert(e900_submit_get(buf,0)>0);n=e900_submit_count;prepare();rdma_config(1,1);assert(e900_submit_count==n);
 assert(e900_submit_data(buf,0)>0);e900_submit_page=512;assert(e900_submit_data(buf,0)==-EINVAL);
 assert(!e900_submit_set("1",0));prepare();rdma_config(1,1);rdma_clear(1);assert(e900_submit_rows[8].kind==3&&e900_submit_rows[8].value==1&&!e900_submit_pending[1]);
 assert(!e900_submit_set("0",0));assert(!e900_submit_set("1",0));e900_submit_count=E900_SUBMIT_CAP-4;prepare();rdma_config(1,1);assert(e900_submit_count==E900_SUBMIT_CAP-4&&e900_submit_status==2&&e900_submit_overflow==1);/* never export a partial batch */
 assert(!e900_submit_set("1",0));prepare();rdma_config(1,1);e900_submit_count=E900_SUBMIT_CAP;e900_submit_end(1,0,2);assert(e900_submit_overflow&&e900_submit_status==2);
 assert(e900_submit_set("2",0)==-EINVAL);cpu=0x21;assert(e900_submit_set("1",0)==-ENODEV);
 /* Every exported row fits even at all-ones field values, including sysfs newline. */
 cpu=0x2a;reset();e900_submit_status=2;e900_submit_count=8;e900_submit_generation=~0u;
 for(i=0;i<8;i++)memset(&e900_submit_rows[i],0xff,sizeof e900_submit_rows[i]);assert(e900_submit_data(buf,0)<4095);
 assert(!e900_submit_selected(0x1aa7)&&!e900_submit_selected(0xdead)&&e900_submit_selected(0x3d6d)&&e900_submit_selected(0x3800)&&e900_submit_selected(0x1da5));
 reset();cpu=0x2a;assert(!e900_submit_set("1",0));prepare();rdma_config(1,1);prepare();rdma_config(1,1);
 assert(e900_submit_rows[8].kind==3&&e900_submit_rows[8].value==5&&e900_submit_pending[1]==2);
 e900_submit_end(1,0x1000000,2);assert(e900_submit_rows[17].batch==2&&e900_submit_rows[17].kind==2);
 assert(!depth);return 0;
}
'''
 (r/'test.c').write_text(c)
 for std in ('gnu89','gnu99'):
  subprocess.run([shutil.which('clang') or 'cc','-std='+std,'-Wall','-Wextra','-Werror',str(r/'test.c'),'-o',str(r/'test')],check=True);subprocess.run([str(r/'test')],check=True)
print('PASS: actual config MMIO/return traces unchanged; ordered repeated coefficients, IRQ/clear attribution, bounds, generation and opt-in isolation; ARM pending')
