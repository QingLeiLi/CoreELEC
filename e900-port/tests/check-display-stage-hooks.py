#!/usr/bin/env python3
"""Compile the real bounded stage hooks; hardware reads are counted mocks."""
from pathlib import Path
import hashlib,json,os,re,shutil,subprocess,tempfile
PORT=Path(__file__).resolve().parents[1]
AUDIT=Path(os.environ.get('E900_AUDIT_ROOT',PORT.parent/'coreelec-audit'))
HW='drivers/amlogic/media/video_sink/video_hw.c'
OPS='drivers/amlogic/media/common/arch/registers/register_ops.c'
def function(source,name):
 m=re.search(r'^(?:static )?(?:unsigned int|bool|int|void) '+name+r'\([^;]*?\)\s*\{',source,re.M)
 assert m,name
 p=source.index('{',m.start());end=p+1;depth=1
 while depth:
  depth+=(source[end]=='{')-(source[end]=='}');end+=1
 return source[m.start():end]+'\n'
with tempfile.TemporaryDirectory(prefix='e900-stage-hooks-') as directory:
 root=Path(directory)
 for row in json.loads((PORT/'tests/source-fixtures.json').read_text()):
  if row['repo']!='CoreELEC/linux-amlogic':continue
  data=(AUDIT/'sources'/row['path'].replace('/','__')).read_bytes()
  assert hashlib.sha256(data).hexdigest()==row['sha256']
  p=root/row['path'];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
 for patch in sorted((PORT/'patches/linux').glob('*.patch')):
  subprocess.run(['git','apply',str(patch)],cwd=root,check=True)
 hw=(root/HW).read_text();ops=(root/OPS).read_text()
 hooks=hw[hw.index('/* E900 stage probes:'):hw.index('\nstatic bool bypass_cm;')]
 assert 'WRITE_VCBUS' not in hooks and 'WR_MPEG' not in hooks
 assert hw.count('e900_stage_input(layer_id, vf, layer, update_mif);')==1
 assert hw.count('e900_stage_output(vpp_misc_set);')==1
 assert hw.count('e900_stage_init("before");')==1
 assert hw.count('e900_stage_init("after");')==1
 c=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <stdarg.h>
typedef uint32_t u32;typedef uint8_t u8;
#define BUS_MAX 17
#define IO_VC_BUS 4
#define IO_HHI_BUS 2
#define IO_DMC_BUS 14
#define IO_AIU_BUS 8
#define MESON_CPU_MAJOR_ID_G12A 0x28
#define AIU_AIFIFO_CTRL 0
#define AIU_MEM_AIFIFO_MEM_CTL 255
#define CODEC_OPS_START(...) ((void)0)
#define CODEC_OPS_ERROR(...) ((void)0)
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define VIDTYPE_COMPRESS (1U<<20)
#define module_param_cb(...)
#define MODULE_PARM_DESC(...)
#define VPP_SC_MISC 0x1d19
#define VPP_HSC_START_PHASE_STEP 0x1d13
#define VPP_VSC_START_PHASE_STEP 0x1d08
#define VPP_MATRIX_CTRL 0x1d5f
#define VPP_MISC 0x1d26
#define VPP_POSTBLEND_VD1_H_START_END 0x1d1c
#define VPP_POSTBLEND_VD1_V_START_END 0x1d1d
struct kernel_param {void *arg;};
struct kernel_param_ops {int (*set)(const char*,const struct kernel_param*);int (*get)(char*,const struct kernel_param*);};
static int param_get_uint(char *b,const struct kernel_param *p){return sprintf(b,"%u",*(unsigned*)p->arg);}
static int kstrtouint(const char *s,unsigned base,unsigned *out){char *e;unsigned long n=strtoul(s,&e,base);if(e==s||(*e&&*e!='\n'))return -EINVAL;if(n>UINT32_MAX)return -ERANGE;*out=n;return 0;}
static unsigned cmpxchg(unsigned *p,unsigned old,unsigned value){unsigned seen=*p;if(seen==old)*p=value;return seen;}
static unsigned cpu=0x2a,live_reads,shadow_reads,log_lines,hw_writes;
static bool is_meson_gxlx2_cpu(void){return cpu==0x2a;}
static unsigned get_cpu_type(void){return cpu;}
static bool legacy_vpp=true,gxlx2_g12_mif;
struct hw_vd_reg_s {unsigned vd_if0_gen_reg,vd_if0_canvas0,viu_vd_fmt_ctrl,vd_if0_luma_x0,vd_if0_luma_y0,vd_if0_gen_reg2,vd_if0_gen_reg3,vd_if0_luma_fifo_size;};
struct vframe_s {unsigned index,pts,width,height,type,bitdepth,canvas0Addr;};
struct video_layer_s {struct hw_vd_reg_s vd_mif_reg;struct vframe_s *dispbuf,*vf_ext;bool switch_vf,enabled,vd1_vd2_mux;unsigned disp_canvas[2][2],cur_canvas_id;};
static struct video_layer_s vd_layer[2];
static struct {unsigned vpp_off;} video_dev,*cur_dev=&video_dev;
struct chip_register_ops {void (*write)(unsigned,unsigned);int w_cnt,ext_offset;};
static struct chip_register_ops *amports_ops[BUS_MAX];
typedef struct {int value;} atomic_t;
static atomic_t e900_bus_write_drops[BUS_MAX];
static int atomic_read(atomic_t *a){return a->value;}
static void atomic_inc(atomic_t *a){a->value++;}
static bool codec_reg_bus_ready(u32 bus){return bus<BUS_MAX && amports_ops[bus];}
static void fake_write(unsigned reg,unsigned val){(void)reg;(void)val;hw_writes++;}
static unsigned live(unsigned r){assert(r>=0x1a50&&r<=0x1d5f);live_reads++;return r;}
static unsigned shadow(unsigned r){shadow_reads++;return r+1;}
#define READ_VCBUS_REG(r) live(r)
#define VSYNC_RD_MPEG_REG(r) shadow(r)
static void record(const char *fmt,...) __attribute__((format(printf,1,2)));
static void record(const char *fmt,...){char b[1024];va_list a;va_start(a,fmt);vsnprintf(b,sizeof b,fmt,a);va_end(a);assert(strstr(b,"e900-stage"));log_lines++;}
#define pr_info(...) record(__VA_ARGS__)
'''
 c+=function(ops,'codec_reg_bus_dropped_writes')+function(ops,'codec_reg_write')+hooks+r'''
int main(void){
 struct kernel_param p={&gxlx2_stage_samples};char b[32];
 struct chip_register_ops valid={fake_write,0,0};
 struct vframe_s vf={1,9000,1280,720,0,8,0x123};
 struct video_layer_s *l=&vd_layer[0];
 l->dispbuf=&vf;l->enabled=true;
 l->vd_mif_reg=(struct hw_vd_reg_s){.vd_if0_gen_reg=0x1a50,.vd_if0_canvas0=0x1a51,.viu_vd_fmt_ctrl=0x1a68,.vd_if0_luma_x0=0x1a53,.vd_if0_luma_y0=0x1a55,.vd_if0_gen_reg2=0x1a6d,.vd_if0_gen_reg3=0x1aa7,.vd_if0_luma_fifo_size=0x1a63};
 assert(!gxlx2_stage_samples&&!e900_stage_input_left);
 e900_stage_output(0);e900_stage_input(0,&vf,l,true);assert(!live_reads&&!log_lines);
 assert(e900_stage_sample_ops.set("9",&p)==-ERANGE);
 assert(e900_stage_sample_ops.set("bad",&p)==-EINVAL);
 assert(!gxlx2_stage_samples);
 codec_reg_write(IO_VC_BUS,0x1d19,7);assert(codec_reg_bus_dropped_writes(IO_VC_BUS)==1&&!hw_writes);
 assert(!codec_reg_bus_dropped_writes(BUS_MAX));
 cpu=0x21;codec_reg_write(IO_VC_BUS,0x1d19,7);assert(!codec_reg_bus_dropped_writes(IO_VC_BUS));
 assert(!e900_stage_sample_ops.set("8",&p));e900_stage_input(0,&vf,l,true);e900_stage_output(0);assert(!live_reads&&!log_lines);
 cpu=0x2a;e900_stage_init("before");assert(log_lines==1&&!live_reads);
 /* Unpublished callback: never perform hardware readback. */
 e900_stage_output(0);assert(!live_reads);
 amports_ops[IO_VC_BUS]=&valid;
 codec_reg_write(IO_VC_BUS,0x1d19,7);assert(hw_writes==1&&valid.w_cnt==1&&codec_reg_bus_dropped_writes(IO_VC_BUS)==1);
 for(unsigned reason=0;reason<8;reason++){
  assert(!e900_stage_sample_ops.set("1",&p));
  legacy_vpp=reason!=0;gxlx2_g12_mif=reason==1;l->vd1_vd2_mux=reason==2;
  l->enabled=reason!=3;l->dispbuf=reason==4?NULL:&vf;vf.type=reason==5?VIDTYPE_COMPRESS:0;
  l->vd_mif_reg.vd_if0_gen_reg=reason==6?0x3200:0x1a50;cur_dev->vpp_off=reason==7?1:0;
  e900_stage_output(0);assert(!live_reads&&!gxlx2_stage_samples);
 }
 legacy_vpp=true;gxlx2_g12_mif=false;l->vd1_vd2_mux=false;l->enabled=true;l->dispbuf=&vf;vf.type=0;cur_dev->vpp_off=0;
 assert(!e900_stage_sample_ops.set("8",&p));
 for(unsigned i=0;i<12;i++){e900_stage_input(0,&vf,l,true);e900_stage_output(0x1234);}
 assert(!gxlx2_stage_samples&&!e900_stage_input_left);
 assert(live_reads==15*8 && shadow_reads==6*8 && hw_writes==1);
 assert(e900_stage_sample_ops.get(b,&p)>0&&!strcmp(b,"0"));
 assert(!e900_stage_sample_ops.set("8",&p));assert(!e900_stage_sample_ops.set("0",&p));
 e900_stage_output(0);e900_stage_input(0,&vf,l,true);assert(live_reads==15*8);
 return 0;
}
'''
 source=root/'test.c';source.write_text(c)
 subprocess.run([shutil.which('clang') or 'cc','-std=gnu99','-Wall','-Wextra','-Werror',str(source),'-o',str(root/'test')],check=True)
 subprocess.run([str(root/'test')],check=True)
print('PASS: all patches apply; real stage hooks are default-off, bounded and read-only; absent buses/other CPUs/inactive or unsupported video cause no hardware reads')
print('PASS: lost-write accounting preserves dispatch and other CPUs; this is a host test, ARM build and hardware localization remain pending')
