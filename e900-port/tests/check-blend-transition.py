#!/usr/bin/env python3
"""Execute actual fixed-point recorder, queue boundary, lease and safety guards."""
from pathlib import Path
import os,json,shutil,subprocess,tempfile,re
P=Path(__file__).resolve().parents[1];A=Path(os.environ.get('E900_AUDIT_ROOT',P.parent/'coreelec-audit'))
def function(s,name):
 m=re.search(r'^(?:static )?void '+name+r'\([^;]*?\)\s*\{',s,re.M);assert m,name
 a=s.index('{',m.start());b=a+1;n=1
 while n:n+=(s[b]=='{')-(s[b]=='}');b+=1
 return s[m.start():b]
with tempfile.TemporaryDirectory(prefix='e900-edge-') as td:
 r=Path(td)
 for row in json.loads((P/'tests/source-fixtures.json').read_text()):
  if row['repo']=='CoreELEC/linux-amlogic':
   f=r/row['path'];f.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(A/'sources'/row['path'].replace('/','__'),f)
 for p in sorted((P/'patches/linux').glob('*.patch')):subprocess.run(['git','apply',str(p)],cwd=r,check=True)
 hw=(r/'drivers/amlogic/media/video_sink/video_hw.c').read_text();edge=(r/'drivers/amlogic/media/video_sink/e900_edge_probe.h').read_text();pixel=(r/'drivers/amlogic/media/video_sink/e900_pixel_probe.h').read_text();rdma=(r/'drivers/amlogic/media/common/rdma/rdma.c').read_text();csc=(r/'drivers/amlogic/media/enhancement/amvecm/amcsc.c').read_text()
 assert hw.index('e900_edge_hook(vinfo, 0,')<hw.index('vpp_misc_set = e900_blend_hold_apply')<hw.index('e900_edge_hook(vinfo, 1,')
 assert hw.index('e900_edge_before_disable(layer_id, on);')<hw.index('e900_pixel_before_disable(layer_id, on);')
 assert 'pr_info(' not in edge and 'WRITE_VCBUS_REG(VPP_MISC' not in edge
 dispatch_start=csc.index('\t\tif (cpu_after_eq(MESON_CPU_MAJOR_ID_G12A) &&\n\t\t(get_cpu_type() != MESON_CPU_MAJOR_ID_TL1)) {')
 dispatch_end=csc.index('\n\t\tcur_hdr_policy',dispatch_start)
 dispatch=csc[dispatch_start:dispatch_end]
 fake_start=csc.index('\t\t\t\tif (vd_path == VD1_PATH && e900_edge_tracking())',csc.index('if (send_fake_frame)'))
 fake_end=csc.index('}',fake_start)+1
 fake=csc[fake_start:fake_end]
 c=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;typedef uint64_t u64;
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define PAGE_SIZE 4096
#define scnprintf snprintf
#define module_param_cb(...)
#define MODULE_PARM_DESC(...)
#define EXPORT_SYMBOL(...)
#define DEFINE_SPINLOCK(n) int n
#define spin_lock_irqsave(l,f) do{(void)(l);(f)=0;assert(!locked);locked=true;}while(0)
#define spin_unlock_irqrestore(l,f) do{(void)(l);(void)(f);assert(locked);locked=false;}while(0)
#define IO_VC_BUS 4
#define VIDTYPE_COMPRESS 0x100000
#define VIDTYPE_MVC 0x1000
#define VIDEO_ENABLE_STATE_IDLE 0
#define VPU_VIU_VD1 2
#define VPU_MEM_POWER_ON 0
#define VPP_MATRIX_CTRL 0x1d5f
#define VPP_MATRIX_PROBE_POS 0x1d5e
#define VPP_MATRIX_PROBE_COLOR 0x1d5c
#define VPP_FIFO_STATUS 0x1d28
#define VPP_MISC 0x1d26
#define VPP_DUMMY_DATA1 0x1d69
#define VPP_CLIP_MISC0 0x1dd9
#define VPP_CLIP_MISC1 0x1dda
#define VIU_MISC_CTRL0 0x1a06
#define VIU_MISC_CTRL1 0x1a07
#define VPP_GCLK_CTRL0 0x1d72
#define VPP_GCLK_CTRL1 0x1d73
#define VPP_SC_GCLK_CTRL 0x1d74
struct kernel_param{void*arg;};
struct kernel_param_ops{int(*set)(const char*,const struct kernel_param*);int(*get)(char*,const struct kernel_param*);};
static int param_get_uint(char*b,const struct kernel_param*k){return sprintf(b,"%u",*(unsigned*)k->arg);}
static int kstrtouint(const char*s,int base,unsigned*v){char*e;unsigned long x=strtoul(s,&e,base);if(e==s||*e||x>0xfffffffful||*s=='-')return -EINVAL;*v=x;return 0;}
struct vframe_s{unsigned width,height,type,index,pts;};
struct vinfo_s{unsigned width,height,field_height;};
struct video_layer_s{struct vframe_s*dispbuf,*vf_ext;bool switch_vf,vd1_vd2_mux,enabled;struct{unsigned vd_if0_gen_reg,vd_if0_gen_reg3;}vd_mif_reg;bool global_output,disable_video,enabled_status_saved;unsigned onoff_state;};
static struct video_layer_s vd_layer[1];static struct vframe_s frame;static struct vinfo_s vi;
static struct{unsigned vpp_off;}dev,*cur_dev=&dev;
static bool legacy_vpp,gxlx2_g12_mif,bus,locked,local,signal_good;
static unsigned cpu,e900_stage_epoch,tick,reads,writes,colors,selector_reads,ctrl,pos,live,queued;
static int mem;
static unsigned video_process_status[1],video_process_flags[1],null_vf_cnt[1];
static bool video_on[1],video_layer_wait_on[1];
static unsigned e900_csc_last_branch,e900_csc_post_count,e900_csc_legacy_count,e900_csc_fake_count;
static int irq_count[2],vsync_cfg_count[2];static unsigned force_rdma_config[2];static bool rdma_done[2];
static bool is_meson_gxlx2_cpu(void){return cpu==0x2a;}
static bool codec_reg_bus_ready(unsigned b){assert(b==4);return bus;}
static bool is_local_vf(struct vframe_s*f){(void)f;return local;}
static int get_vpu_mem_pd_vmod(unsigned n){assert(n==2);return mem;}
static const struct vinfo_s*get_current_vinfo(void){return &vi;}
static u64 get_jiffies_64(void){return 100+tick;}
static unsigned read_reg(unsigned reg){
 assert(locked&&cpu==0x2a&&bus&&!mem);reads++;
 switch(reg){case VPP_MATRIX_CTRL:selector_reads++;return ctrl;case VPP_MATRIX_PROBE_POS:selector_reads++;return pos;
 case VPP_MATRIX_PROBE_COLOR:colors++;return signal_good?0xac200200:0;
 case 0x1dd7:colors++;return signal_good?0x80000003:0;
 case 0x1a50:return 0x38400043;case 0x1aa7:return 0x33;case 0x1a68:return 0x20310c11;
 case VPP_DUMMY_DATA1:case VPP_CLIP_MISC0:case VPP_CLIP_MISC1:case VIU_MISC_CTRL0:case VIU_MISC_CTRL1:case VPP_GCLK_CTRL0:case VPP_GCLK_CTRL1:case VPP_SC_GCLK_CTRL:case 0x1d79:return 0x5678;
 case 0x1a63:return 0xff00c0;case VPP_FIFO_STATUS:return 0x1234;case VPP_MISC:return live;}
 switch(reg){case 0x1a51:case 0x1a6d:case 0x1a53:case 0x1a54:case 0x1a55:case 0x1a56:case 0x1a69:case 0x1a6a:case 0x1d19:case 0x1d01:case 0x1d02:case 0x1d13:case 0x1d08:case 0x1d18:case 0x1d0d:case 0x1da5:return reg^0xdead0000;}
 assert(0);return 0;
}
static void write_reg(unsigned reg,unsigned val){assert(locked&&bus&&!mem);writes++;if(reg==VPP_MATRIX_CTRL)ctrl=val;else{assert(reg==VPP_MATRIX_PROBE_POS);pos=val;}}
#define READ_VCBUS_REG read_reg
#define WRITE_VCBUS_REG write_reg
static unsigned VSYNC_RD_MPEG_REG(unsigned r){assert(r==VPP_MISC);return queued;}
'''+function(rdma,'e900_rdma_progress')+'\n'+function(csc,'e900_csc_progress')+'\n'+pixel+'\n'+edge+'''\n#define MESON_CPU_MAJOR_ID_G12A 0x28\n#define MESON_CPU_MAJOR_ID_TL1 0x2e\n#define VD1_PATH 0\nstatic unsigned dispatch_post,dispatch_legacy;\nstatic unsigned get_cpu_type(void){return cpu;}\nstatic bool cpu_after_eq(unsigned n){return cpu>=n;}\nstatic void video_post_process(int vf,...){(void)vf;dispatch_post++;}\nstatic void video_process(int vf,...){(void)vf;dispatch_legacy++;}\nstatic void run_dispatch(unsigned chip,bool active,unsigned path){\n int vf=0,csc_type=0,vinfo=0,p=0,signal_change_flag=0,source_format[2]={0,0};unsigned vd_path=path;cpu=chip;e900_edge_reserved=active;\n'''+dispatch+'''\n}\nstatic void run_fake(bool active,unsigned path){unsigned vd_path=path;e900_edge_reserved=active;\n'''+fake+'''\n}\n'''+r'''
static void reset(void){
 video_process_status[0]=2;video_process_flags[0]=0x55;null_vf_cnt[0]=3;video_on[0]=true;video_layer_wait_on[0]=false;
 e900_csc_last_branch=1;e900_csc_post_count=4;e900_csc_legacy_count=5;e900_csc_fake_count=6;
 cpu=0x2a;legacy_vpp=bus=signal_good=true;gxlx2_g12_mif=locked=local=false;mem=0;tick=reads=writes=colors=selector_reads=0;dev.vpp_off=0;e900_stage_epoch=1;
 frame=(struct vframe_s){1280,720,0,1,0};vi=(struct vinfo_s){1920,1080,1080};
 vd_layer[0]=(struct video_layer_s){.dispbuf=&frame,.enabled=true,.vd_mif_reg={0x1a50,0x1aa7},.global_output=true,.enabled_status_saved=true};
 ctrl=0x80407003;pos=0xa000e001;live=queued=0x100054b0;
 e900_pixel_status=e900_pixel_count=0;e900_pixel_owned=e900_pixel_cancel=e900_pixel_restored=false;
 e900_edge_reserved=e900_edge_cancel=e900_edge_seen_off=false;e900_edge_status=e900_edge_count=e900_edge_tick=0;e900_edge_register_only=false;
 irq_count[0]=10;vsync_cfg_count[0]=11;rdma_done[0]=true;force_rdma_config[0]=0;
}
static void step(void){
 tick++;frame.index++;frame.pts+=3000;live=queued;irq_count[0]++;vsync_cfg_count[0]++;
 e900_edge_hook(&vi,0,live,false);
 vd_layer[0].enabled=vd_layer[0].global_output;
 queued=vd_layer[0].global_output?0x100054b0:0x100010b0;
 e900_edge_hook(&vi,1,queued,false);
}
int main(void){
 unsigned i,j,mode,before,old_ctrl,old_pos,n;char buf[PAGE_SIZE];struct kernel_param kp={&e900_edge_page};
 assert(e900_edge_ops.set==e900_edge_set&&e900_edge_ops.get==e900_edge_get&&e900_edge_page_ops.set==e900_edge_page_set&&e900_edge_page_ops.get==param_get_uint&&e900_edge_data_ops.get==e900_edge_data_get);
 assert(e900_edge_regs_ops.get==e900_edge_regs_get);
 assert(e900_pixel_scan_ops.set==e900_pixel_scan_set&&e900_pixel_page_ops.set==e900_pixel_page_set&&e900_pixel_data_ops.get==e900_pixel_data_get);
 reset();step();e900_pixel_step(&vi);assert(!reads&&!writes);assert(e900_edge_set("3",NULL)==-EINVAL);
 cpu=0x21;assert(e900_edge_set("1",NULL)==-ENODEV);
 for(mode=1;mode<=2;mode++)for(j=0;j<14;j++){
  reset();assert(!e900_edge_set(mode==1?"1":"2",NULL));
  switch(j){case 0:cpu=0x21;break;case 1:legacy_vpp=false;break;case 2:gxlx2_g12_mif=true;break;case 3:vd_layer[0].vd1_vd2_mux=true;break;case 4:vd_layer[0].dispbuf=NULL;break;case 5:local=true;break;case 6:vd_layer[0].disable_video=true;break;case 7:vd_layer[0].enabled_status_saved=false;break;case 8:bus=false;break;case 9:mem=1;break;case 10:mem=-1;break;case 11:vd_layer[0].vd_mif_reg.vd_if0_gen_reg=0x3210;break;case 12:frame.type=VIDTYPE_COMPRESS;break;case 13:vi.field_height=540;break;}
  e900_edge_hook(&vi,0,0,false);assert(e900_edge_status==5&&!reads&&!writes);assert(!e900_edge_records[0].flags);
 }
 reset();assert(!e900_edge_set("1",NULL));assert(e900_pixel_scan_set("1",NULL)==-EBUSY);assert(e900_edge_set("1",NULL)==-EBUSY);old_ctrl=ctrl;old_pos=pos;
 step();step();assert(!colors);e900_note_pps(0,1);step();assert(colors==4);assert(e900_edge_records[4].pps_calls==1&&e900_edge_records[4].sr_support==0&&e900_edge_records[4].sr_refresh==1);assert(e900_edge_records[4].csc_status==2&&e900_edge_records[4].csc_flags==0x55&&e900_edge_records[4].csc_post==4&&e900_edge_records[4].csc_legacy==5&&e900_edge_records[4].csc_fake==6);assert(e900_edge_records[4].flags==7);
 vd_layer[0].global_output=false;step();assert(!vd_layer[0].enabled&&e900_edge_status==2);
 assert(e900_edge_records[7].global==0&&e900_edge_records[7].enabled==0&&e900_edge_records[7].flags==7);
 assert(e900_edge_records[7].live==0x100054b0&&e900_edge_records[7].wanted==0x100010b0&&e900_edge_records[7].shadow==0x100010b0);
 step();assert(e900_edge_records[8].live==0x100010b0);
 vd_layer[0].global_output=true;step();assert(e900_edge_status==2);/* pre:enabled0/global1 is the exact restoration boundary */
 assert(e900_edge_records[10].enabled==0&&e900_edge_records[10].global==1&&e900_edge_records[10].flags==7);
 for(i=0;i<16;i++)step();assert(e900_edge_status==3&&!e900_edge_reserved&&!e900_pixel_owned&&e900_pixel_restored&&ctrl==old_ctrl&&pos==old_pos);
 before=reads;step();assert(reads==before);n=e900_pps_calls;e900_note_pps(3,0);assert(e900_pps_calls==n);
 for(i=0;i<e900_edge_count;i++)assert(e900_edge_records[i].irq&&e900_edge_records[i].configured);
 assert(e900_edge_get(buf,NULL)>0&&strstr(buf,"status=3"));assert(e900_edge_page_set("64",NULL)==-EINVAL);
 assert(!e900_edge_page_set("0",NULL));n=e900_edge_data_get(buf,&kp);assert(n>0&&n<PAGE_SIZE);
 reset();e900_edge_set("1",NULL);step();step();signal_good=false;step();assert(e900_edge_records[4].flags==7&&!e900_edge_records[4].raw0&&!e900_edge_records[4].raw1);/* zero is preserved, never auto-classified valid black */
 reset();e900_edge_set("1",NULL);step();before=reads;bus=false;e900_edge_hook(&vi,0,0,false);assert(e900_edge_status==6&&reads==before);bus=true;step();assert(e900_edge_status==5&&!e900_pixel_owned&&e900_pixel_restored);
 reset();e900_edge_set("1",NULL);step();before=reads;mem=1;e900_edge_hook(&vi,0,0,false);assert(e900_edge_status==6&&reads==before);mem=0;step();assert(!e900_pixel_owned);
 reset();e900_edge_set("1",NULL);step();ctrl=(ctrl&~E900_PIXEL_SELECT_MASK)|(3<<10);step();assert(e900_edge_status==5&&!e900_pixel_restored&&((ctrl>>10)&63)==3);
 reset();e900_edge_set("1",NULL);step();e900_edge_before_disable(0,false);assert(e900_edge_status==6);e900_pixel_before_disable(0,false);assert(!e900_pixel_owned&&e900_pixel_restored);step();assert(e900_edge_status==5&&!e900_edge_reserved);
 reset();e900_edge_set("1",NULL);step();e900_edge_set("0",NULL);step();assert(e900_edge_status==4&&!e900_pixel_owned&&e900_pixel_restored);
 reset();e900_edge_set("1",NULL);step();frame.width=640;step();assert(e900_edge_status==5&&e900_edge_reason==7&&e900_pixel_restored);
 reset();e900_pixel_scan_set("1",NULL);assert(e900_edge_set("1",NULL)==-EBUSY);
 reset();e900_edge_set("1",NULL);for(i=0;i<256;i++)step();assert(e900_edge_status==3&&e900_edge_reason==2&&e900_edge_count==512&&e900_pixel_restored);
 memset(e900_edge_records,0xff,sizeof(e900_edge_records));e900_edge_generation=0xffffffff;
 for(i=0;i<64;i++){char page[8];sprintf(page,"%u",i);assert(!e900_edge_page_set(page,NULL));n=e900_edge_data_get(buf,NULL);assert(n>0&&n<PAGE_SIZE);}
 for(i=0x20;i<=0x30;i++)for(j=0;j<4;j++){
  bool active=!!(j&1);unsigned path=(j>>1)&1;bool post=i>=0x28&&i!=0x2e;
  dispatch_post=dispatch_legacy=e900_csc_post_count=e900_csc_legacy_count=e900_csc_fake_count=0;
  run_dispatch(i,active,path);assert(dispatch_post==(unsigned)post&&dispatch_legacy==(unsigned)!post);
  assert(e900_csc_post_count==(unsigned)(active&&!path&&post));assert(e900_csc_legacy_count==(unsigned)(active&&!path&&!post));
  run_fake(active,path);assert(e900_csc_fake_count==(unsigned)(active&&!path));
 }

 /* Mode2: same actual guard/hook; no selector/color accesses or writes. */
 reset();old_ctrl=ctrl;old_pos=pos;assert(!e900_edge_set("2",NULL));assert(e900_pixel_scan_set("1",NULL)==-EBUSY);
 step();step();assert(e900_edge_regs_get(buf,NULL)==-EBUSY);
 vd_layer[0].global_output=false;step();step();assert(e900_edge_records[7].flags==1&&e900_edge_status==2);
 assert(e900_edge_records[7].registers[1]==(0x1a6d^0xdead0000));
 vd_layer[0].global_output=true;step();assert(e900_edge_status==2);for(i=0;i<16;i++)step();
 assert(e900_edge_status==3&&!e900_edge_reserved&&!e900_pixel_owned&&e900_pixel_restored);
 assert(!writes&&!colors&&!selector_reads&&ctrl==old_ctrl&&pos==old_pos);
 assert(!e900_edge_page_set("0",NULL));assert(e900_edge_regs_get(buf,NULL)>0);assert(strstr(buf,"dead1a6d"));
 assert(e900_edge_get(buf,NULL)>0&&strstr(buf,"mode=2"));
 for(i=0;i<e900_edge_count;i++)assert(e900_edge_records[i].flags==1&&!e900_edge_records[i].ctrl&&!e900_edge_records[i].raw0);
 /* Unsafe mode2 termination performs no further VD1 reads or restoration writes. */
 for(j=0;j<5;j++){
  reset();e900_edge_set("2",NULL);step();before=reads;
  switch(j){case 0:mem=1;break;case 1:bus=false;break;case 2:local=true;break;case 3:vd_layer[0].dispbuf=NULL;break;case 4:vd_layer[0].disable_video=true;break;}
  e900_edge_hook(&vi,0,0,false);assert(e900_edge_status==5&&!e900_edge_reserved&&reads==before&&!writes&&!selector_reads);
 }
 reset();e900_edge_set("2",NULL);step();before=reads;e900_edge_before_disable(0,false);assert(e900_edge_status==5&&reads==before&&!writes);
 reset();e900_edge_set("2",NULL);e900_edge_set("0",NULL);assert(e900_edge_status==4&&!e900_edge_reserved&&!reads&&!writes);
 reset();e900_edge_set("2",NULL);step();e900_edge_set("0",NULL);step();assert(e900_edge_status==4&&!writes&&!selector_reads);
 reset();e900_edge_set("2",NULL);for(i=0;i<260;i++)step();assert(e900_edge_count==512&&e900_edge_status==3&&!writes);
 assert(!e900_edge_page_set("63",NULL));n=e900_edge_regs_get(buf,NULL);assert(n>0&&n<PAGE_SIZE);
 reset();e900_edge_set("1",NULL);assert(e900_edge_regs_get(buf,NULL)==-EINVAL);
 return 0;
}
'''
 (r/'test.c').write_text(c)
 for std in ['gnu89','gnu99']:
  subprocess.run([shutil.which('clang') or 'cc','-std='+std,'-Wall','-Wextra','-Werror',str(r/'test.c'),'-o',str(r/'test')],check=True)
  subprocess.run([str(r/'test')],check=True)
print('PASS: actual transition recorder; delayed queue latch, disabled-blend reads,14 rejection states, leases, contention, deferred restore,512-row bound; mode2 global-off/restore, Stop guards and ZERO selector/color reads/writes; ARM/hardware pending')
