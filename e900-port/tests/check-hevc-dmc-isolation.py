#!/usr/bin/env python3
"""Execute actual HEVC/VLD DMC functions; no hardware or pixel claim."""
import hashlib,json,os,re,shutil,subprocess,tempfile
from pathlib import Path
P=Path(__file__).resolve().parents[1]
A=Path(os.environ.get('E900_AUDIT_ROOT',P.parent/'coreelec-audit'))
FILE='drivers/frame_provider/decoder/utils/vdec.c'
PATCH='0004-gxlx2-hevc-dmc-vpu-port-isolation.patch'
def function(s,name):
 m=re.search(r'^static (?:void|unsigned int) '+name+r'\([^;]*?\)\s*\{',s,re.M);assert m,name
 a=s.index('{',m.start());b=a+1;n=1
 while n:n+=(s[b]=='{')-(s[b]=='}');b+=1
 return s[m.start():b]
with tempfile.TemporaryDirectory(prefix='e900-hevc-dmc-') as td:
 r=Path(td)
 manifest=json.loads((P/'tests/source-fixtures.json').read_text())
 repo=next(x['repo'] for x in manifest if x['path']==FILE)
 for row in manifest:
  if row['repo']!=repo:continue
  f=A/'sources'/row['path'].replace('/','__');assert hashlib.sha256(f.read_bytes()).hexdigest()==row['sha256']
  d=r/row['path'];d.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,d)
 for patch in sorted((P/'patches/media').glob('*.patch')):
  if patch.name==PATCH:old=(r/FILE).read_text()
  subprocess.run(['git','apply',str(patch)],cwd=r,check=True)
 new=(r/FILE).read_text()
 restored=new.replace('\t\t/* GXLX2 bit8 is the legacy VPU read port, not HEVCB. */\n','').replace('AM_MESON_CPU_MAJOR_ID_G12A &&\n\t\t    get_cpu_major_id() != AM_MESON_CPU_MAJOR_ID_GXLX2)\n\t\t\tmask |= (1 << 8)', 'AM_MESON_CPU_MAJOR_ID_G12A)\n\t\t\tmask |= (1 << 8)')
 assert restored==old,'unexpected edits beyond the two HEVCB selectors'
 code=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#define AM_MESON_CPU_MAJOR_ID_M8B 0x1b
#define AM_MESON_CPU_MAJOR_ID_G12A 0x28
#define AM_MESON_CPU_MAJOR_ID_G12B 0x29
#define AM_MESON_CPU_MAJOR_ID_GXLX2 0x2a
#define AM_MESON_CPU_MAJOR_ID_SC2 0x32
#define VDEC_INPUT_TARGET_VLD 0
#define VDEC_INPUT_TARGET_HEVC 1
#define DMC_REQ_CTRL 0
#define DMC_CHAN_STS 0x32
#define TM2_REVB_DMC_CHAN_STS 0x33
struct vdec_input_s {unsigned target;};
struct vdec_s {struct vdec_input_s input;void *dev;};
static unsigned cpu,req,stops,pipeline,reads,writes,tm2b;
static unsigned get_cpu_major_id(void){return cpu;}
static unsigned get_cpu_type(void){return cpu;}
static bool is_cpu_tm2_revb(void){return tm2b;}
#define IS_ERR_OR_NULL(p) (!(p))
#define pr_debug(...)
#define spin_lock_irqsave(lock,flags) do{(flags)=0;}while(0)
#define spin_unlock_irqrestore(lock,flags) ((void)(flags))
static void vdec_stop_armrisc(unsigned target){(void)target;stops++;}
static void vdec_dmc_pipeline_reset(void){pipeline++;}
static unsigned codec_dmcbus_read(unsigned reg){reads++;return reg==DMC_REQ_CTRL?req:0xffffffffu;}
static void codec_dmcbus_write(unsigned reg,unsigned value){assert(reg==DMC_REQ_CTRL);req=value;writes++;}
'''+function(new,'vdec_vld_dmc_mask')+'\n'
 for label,src in [('baseline',old),('candidate',new)]:
  for name in ['vdec_disable_DMC','vdec_enable_DMC']:
   code+=function(src,name).replace(name,label+'_'+name)+'\n'
 code+=r'''
int main(void){
 unsigned target,on,seed,hasdev,rev;
 const unsigned seeds[]={0,0xffffffffu,0xdeef,0xdfef,0x12345678};
 struct vdec_s v;
 for(cpu=0;cpu<128;cpu++)for(target=0;target<2;target++)
 for(on=0;on<2;on++)for(seed=0;seed<5;seed++)
 for(hasdev=0;hasdev<2;hasdev++)for(rev=0;rev<2;rev++){
  unsigned original=seeds[seed],expected,old_reads,old_writes,old_stops,old_pipeline;
  v.input.target=target;v.dev=hasdev?&v:0;tm2b=rev;
  req=original;reads=writes=stops=pipeline=0;
  if(on)baseline_vdec_enable_DMC(&v);else baseline_vdec_disable_DMC(&v);
  expected=req;old_reads=reads;old_writes=writes;old_stops=stops;old_pipeline=pipeline;
  req=original;reads=writes=stops=pipeline=0;
  if(on)candidate_vdec_enable_DMC(&v);else candidate_vdec_disable_DMC(&v);
  if(cpu==0x2a && target==VDEC_INPUT_TARGET_HEVC){
   assert(req==(on?(original|(1u<<4)):(original&~(1u<<4))));
   assert((req&(1u<<8))==(original&(1u<<8)));
   assert(((req^original)&~(1u<<4))==0);
  }else assert(req==expected);
  assert(reads==old_reads && writes==old_writes && stops==old_stops && pipeline==old_pipeline);
 }
 return 0;
}
'''
 c=r/'test.c';c.write_text(code)
 for std in ['gnu89','gnu99']:
  subprocess.run([shutil.which('clang') or 'cc','-std='+std,'-Wall','-Wextra','-Werror',str(c),'-o',str(r/'test')],check=True)
  subprocess.run([str(r/'test')],check=True,timeout=10)
print('PASS: real DMC stop/start preserves GXLX2 VPU bit8 for HEVC; only bit4 changes; other CPU/target results, read/write/stop/reset counts unchanged')
print('PENDING: GXLX2 port-map hardware confirmation, module ARM build, HEVC end/Stop/replay and GUI/RDMA regression')
