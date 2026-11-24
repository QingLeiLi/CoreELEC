#!/usr/bin/env python3
"""Run the actual fixed VSync pixel scan with a register/scene model."""
from pathlib import Path
import os,json,shutil,subprocess,tempfile
P=Path(__file__).resolve().parents[1];A=Path(os.environ.get('E900_AUDIT_ROOT',P.parent/'coreelec-audit'))
with tempfile.TemporaryDirectory(prefix='e900-pixels-') as d:
 r=Path(d)
 for row in json.loads((P/'tests/source-fixtures.json').read_text()):
  if row['repo']!='CoreELEC/linux-amlogic':continue
  p=r/row['path'];p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(A/'sources'/row['path'].replace('/','__'),p)
 for patch in sorted((P/'patches/linux').glob('*.patch')):subprocess.run(['git','apply',str(patch)],cwd=r,check=True)
 header=(r/'drivers/amlogic/media/video_sink/e900_pixel_probe.h').read_text()
 hw=(r/'drivers/amlogic/media/video_sink/video_hw.c').read_text()
 assert hw.count('e900_pixel_step(vinfo);')==1
 assert hw.index('e900_pixel_before_disable(layer_id, on);')<hw.index('e900_debug_event("layer_switch"')
 c=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <errno.h>
typedef unsigned u32;
#define PAGE_SIZE 4096
#define scnprintf snprintf
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define DEFINE_SPINLOCK(n) int n
#define spin_lock_irqsave(l,f) do{assert(!locked);locked=1;(void)(l);f=0;}while(0)
#define spin_unlock_irqrestore(l,f) do{assert(locked);locked=0;(void)(l);(void)(f);}while(0)
#define module_param_cb(...)
#define MODULE_PARM_DESC(...)
#define VPP_MATRIX_CTRL 0x1d5f
#define VPP_MATRIX_PROBE_POS 0x1d5e
#define VPP_MATRIX_PROBE_COLOR 0x1d5c
#define VIDTYPE_COMPRESS 0x100
#define IO_VC_BUS 1
struct kernel_param{void*arg;};
struct kernel_param_ops{int(*set)(const char*,const struct kernel_param*);int(*get)(char*,const struct kernel_param*);};
static int param_get_uint(char*b,const struct kernel_param*p){return sprintf(b,"%u",*(unsigned*)p->arg);}
static int kstrtouint(const char*s,unsigned base,unsigned*v){char*e;if(*s=='-')return -EINVAL;unsigned long n=strtoul(s,&e,base);if(e==s||*e||n>0xffffffffUL)return -EINVAL;*v=n;return 0;}
struct vframe_s{unsigned width,height,type,index,pts;};
struct mif{unsigned vd_if0_gen_reg,vd_if0_gen_reg3;};
struct video_layer_s{struct vframe_s*dispbuf,*vf_ext;bool switch_vf,vd1_vd2_mux,enabled;struct mif vd_mif_reg;};
struct vinfo_s{unsigned width,height,field_height;};
static struct video_layer_s vd_layer[1];static struct vframe_s frame;static struct vinfo_s info;
static struct{unsigned vpp_off;} dev,*cur_dev=&dev;
static unsigned cpu=0x2a,e900_stage_epoch=1,tick,selected_tick,reads,writes,colors;
static bool legacy_vpp=true,gxlx2_g12_mif,bus=true,locked,drop_select;
static unsigned ctrl,pos;
static bool is_meson_gxlx2_cpu(void){return cpu==0x2a;}
static bool codec_reg_bus_ready(unsigned b){assert(b==IO_VC_BUS);return bus;}
static const struct vinfo_s*get_current_vinfo(void){return &info;}
static unsigned read_reg(unsigned r){
 assert(locked&&cpu==0x2a&&bus);reads++;
 if(r==VPP_MATRIX_CTRL)return ctrl;if(r==VPP_MATRIX_PROBE_POS)return pos;
 assert(vd_layer[0].enabled&&tick>=selected_tick+2);colors++;
 if(r==VPP_MATRIX_PROBE_COLOR)return ((ctrl>>10)&63)<<26|((pos>>16)&8191)<<13|(pos&8191);
 assert(r==0x1dd7);return 0xab000000|((ctrl>>10)&15);
}
static void write_reg(unsigned r,unsigned v){
 assert(locked&&cpu==0x2a&&bus);writes++;
 if(r==VPP_MATRIX_CTRL){if(!drop_select)ctrl=v;}
 else{assert(r==VPP_MATRIX_PROBE_POS);pos=v;selected_tick=tick;}
}
#define READ_VCBUS_REG read_reg
#define WRITE_VCBUS_REG write_reg
'''+header+r'''
static void reset(void){
 memset(e900_pixel_records,0,sizeof(e900_pixel_records));
 cpu=0x2a;legacy_vpp=true;gxlx2_g12_mif=false;bus=true;drop_select=false;locked=false;
 ctrl=0x80407003;pos=0xa000e001;reads=writes=colors=tick=selected_tick=0;e900_stage_epoch=1;dev.vpp_off=0;
 frame=(struct vframe_s){1280,720,0,1,0};info=(struct vinfo_s){1920,1080,1080};
 vd_layer[0]=(struct video_layer_s){&frame,NULL,false,false,true,{0x1a50,0x1aa7}};
 e900_pixel_status=e900_pixel_page=e900_pixel_count=e900_pixel_generation=0;
 e900_pixel_owned=e900_pixel_cancel=e900_pixel_restored=false;
}
static void vsync(void){tick++;frame.index++;frame.pts+=1500;e900_pixel_step(&info);}
int main(void){
 char buf[PAGE_SIZE];struct kernel_param kp={&e900_pixel_page};
 assert(e900_pixel_scan_ops.set==e900_pixel_scan_set&&e900_pixel_page_ops.set==e900_pixel_page_set&&e900_pixel_data_ops.get==e900_pixel_data_get);
 reset();for(unsigned i=0;i<10;i++)vsync();assert(!reads&&!writes);assert(e900_pixel_scan_set("2",NULL)==-EINVAL);
 cpu=0x21;assert(e900_pixel_scan_set("1",NULL)==-ENODEV);cpu=0x2a;
 for(unsigned bad=0;bad<13;bad++){
  reset();switch(bad){case 0:legacy_vpp=false;break;case 1:gxlx2_g12_mif=true;break;case 2:bus=false;break;case 3:vd_layer[0].enabled=false;break;case 4:vd_layer[0].dispbuf=NULL;break;case 5:frame.type=VIDTYPE_COMPRESS;break;case 6:vd_layer[0].vd1_vd2_mux=true;break;case 7:vd_layer[0].vd_mif_reg.vd_if0_gen_reg=0x3200;break;case 8:vd_layer[0].vd_mif_reg.vd_if0_gen_reg3=0x3216;break;case 9:dev.vpp_off=1;break;case 10:frame.width=3840;break;case 11:info.width=3840;break;case 12:info.field_height=540;break;}
  assert(!e900_pixel_scan_set("1",NULL));vsync();assert(e900_pixel_status==5&&!reads&&!writes);
 }
 reset();unsigned old_ctrl=ctrl,old_pos=pos;
 assert(!e900_pixel_scan_set("1",NULL));assert(e900_pixel_scan_set("1",NULL)==-EBUSY);
 for(unsigned i=0;i<257;i++)vsync();assert(e900_pixel_status==3&&e900_pixel_count==128&&!e900_pixel_owned&&e900_pixel_restored);assert(ctrl==old_ctrl&&pos==old_pos&&colors==256);
 for(unsigned i=0;i<128;i++){
  struct e900_pixel_record*r=&e900_pixel_records[i];assert(r->port==e900_pixel_ports[i/16]);assert(r->grid==(i%16)/8);assert(r->x==(2*(i%8)+1)*(r->grid?1920:1280)/16);assert(r->y==(r->grid?540:360));assert(r->raw0==((r->port&63)<<26|r->x<<13|r->y));
 }
 for(unsigned page=0;page<8;page++){char s[8];sprintf(s,"%u",page);assert(!e900_pixel_page_set(s,NULL));int n=e900_pixel_data_get(buf,NULL);assert(n>0&&n<PAGE_SIZE);unsigned lines=0;for(char*p=buf;*p;p++)lines+=*p=='\n';assert(lines==16);}
 assert(e900_pixel_page_set("8",NULL)==-EINVAL);assert(e900_pixel_state_get(buf,NULL)>0);assert(strstr(buf,"status=3"));assert(param_get_uint(buf,&kp)>0);
 reset();old_ctrl=ctrl;old_pos=pos;e900_pixel_scan_set("1",NULL);vsync();e900_pixel_scan_set("0",NULL);vsync();assert(e900_pixel_status==4&&ctrl==old_ctrl&&pos==old_pos&&!e900_pixel_owned);
 reset();old_ctrl=ctrl;old_pos=pos;e900_pixel_scan_set("1",NULL);vsync();e900_pixel_before_disable(0,false);assert(e900_pixel_status==4&&ctrl==old_ctrl&&pos==old_pos);
 reset();e900_pixel_scan_set("1",NULL);vsync();e900_pixel_before_disable(0xff,false);assert(e900_pixel_status==4&&!e900_pixel_owned);
 reset();e900_pixel_scan_set("1",NULL);vsync();bus=false;unsigned before=reads;vsync();assert(e900_pixel_status==6&&reads==before);bus=true;vsync();assert(e900_pixel_status==5&&!e900_pixel_owned);
 reset();e900_pixel_scan_set("1",NULL);vsync();ctrl=(ctrl&~E900_PIXEL_SELECT_MASK)|(3<<10);vsync();assert(e900_pixel_status==5&&!e900_pixel_restored&&((ctrl>>10)&63)==3);
 reset();old_ctrl=ctrl;e900_pixel_scan_set("1",NULL);vsync();e900_stage_epoch++;vsync();assert(e900_pixel_status==5&&ctrl==old_ctrl);
 reset();old_ctrl=ctrl;e900_pixel_scan_set("1",NULL);vsync();ctrl^=1;for(unsigned i=0;i<256;i++)vsync();assert(e900_pixel_status==3&&ctrl==(old_ctrl^1));
 reset();drop_select=true;e900_pixel_scan_set("1",NULL);vsync();vsync();assert(e900_pixel_status==5&&!colors);
 return 0;
}
'''
 kernel_c=c.split('int main(void){',1)[0]+'''int main(void){char b[PAGE_SIZE];struct kernel_param kp={&e900_pixel_page};reset();e900_pixel_scan_ops.set("1",NULL);vsync();e900_pixel_before_disable(0,false);e900_pixel_scan_ops.get(b,NULL);e900_pixel_page_ops.set("0",NULL);e900_pixel_page_ops.get(b,&kp);e900_pixel_data_ops.get(b,NULL);return 0;}'''
 (r/'gnu89.c').write_text(kernel_c);subprocess.run([shutil.which('clang') or 'cc','-std=gnu89','-Wall','-Wextra','-Werror',str(r/'gnu89.c'),'-o',str(r/'gnu89')],check=True);subprocess.run([str(r/'gnu89')],check=True)
 (r/'test.c').write_text(c);subprocess.run([shutil.which('clang') or 'cc','-std=gnu99','-Wall','-Wextra','-Werror',str(r/'test.c'),'-o',str(r/'test')],check=True);subprocess.run([str(r/'test')],check=True)
print('PASS: actual VSync probe state machine; 8 candidate taps/128 sparse points, two-VSync settling, guards, cancellation, pre-disable/deferred restore, contention, readback and paged output. Hardware calibration remains pending.')

# Execute the real userspace collector against a deterministic sysfs model.
import importlib.util
from unittest import mock
spec=importlib.util.spec_from_file_location('pixel_client',P/'scripts/e900-pixel-probe.py');client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)
with tempfile.TemporaryDirectory(prefix='e900-pixel-client-') as d:
 root=Path(d);base=root/'sys/module/amvideo/parameters';base.mkdir(parents=True)
 scan,page,data=[base/x for x in ('gxlx2_pixel_scan','gxlx2_pixel_page','gxlx2_pixel_data')]
 for p in (scan,page,data):p.write_text('')
 real_read=Path.read_text;real_write=Path.write_text
 success=None
 for mode in ('ok','invalid','timeout','generation_change','missing_row'):
  state={'generation':0,'status':0,'count':0,'owned':0,'restored':0,'reason':0,'guard':0};selected=[0];cancelled=[]
  def read(path,*a,**kw):
   if path==scan:return ' '.join(f'{k}={v}' for k,v in state.items())+'\n'
   if path==page:return str(selected[0])+'\n'
   if path==data:
    out=[]
    for i in range(selected[0]*16,selected[0]*16+16):
     if mode=='missing_row' and i==127:continue
     port=list(client.PORTS)[i//16];grid=(i%16)//8;w=1280 if not grid else 1920;x=(2*(i%8)+1)*w//16;y=360 if not grid else 540
     out.append(f'sample={i} generation=1 port={port} grid={grid} x={x} y={y} raw0=12345678 raw1=0000000a frame={i+1} pts={i*1500}')
    if mode=='generation_change' and selected[0]==7:state['generation']=2
    return '\n'.join(out)+'\n'
   return real_read(path,*a,**kw)
  def write(path,value,*a,**kw):
   if path==scan:
    if value.strip()=='1':
     state.update(generation=1,status=5 if mode=='invalid' else 2 if mode=='timeout' else 3,count=128 if mode!='timeout' else 0,owned=1 if mode=='timeout' else 0,restored=0 if mode=='invalid' else 1,reason=3 if mode=='invalid' else 0)
    else:cancelled.append(state['generation']);state['owned']=0
    return len(value)
   if path==page:selected[0]=int(value);return len(value)
   return real_write(path,value,*a,**kw)
  with mock.patch.object(Path,'read_text',read),mock.patch.object(Path,'write_text',write),mock.patch.object(client.time,'sleep'):
   result=client.collect(root,timeout=-1 if mode=='timeout' else 15)
  assert result['status']==('collected_uncalibrated' if mode=='ok' else 'failed'),result
  assert not result['physical_tap_verified'] and result['calibration_status']=='unverified'
  if mode=='ok':
   assert len(result['records'])==128 and selected[0]==0
   success=result
   svg=client.render_svg(result);assert 'NOT a screenshot' in svg and svg.count('<rect ')==257
   import xml.etree.ElementTree as ET
   ET.fromstring(svg)
  if mode=='generation_change':assert not cancelled
 import copy
 other=copy.deepcopy(success);other['records'][0]['raw0']^=1
 comparison=client.compare_scans(success,other);assert comparison['status']=='compared_uncalibrated' and comparison['groups'][0]['changed_raw_pairs']==1 and not comparison['physical_tap_verified']
 other['records'][0]['x']+=1;assert client.compare_scans(success,other)['status']=='incompatible'
 assert client.compare_scans({},success)['status']=='unavailable'
 try:client.decode_record('sample=0')
 except ValueError:pass
 else:raise AssertionError('Accepted incomplete record')
print('PASS: real collector validates pages/generation, rejects failures/timeouts/incomplete results, preserves raw packing alternatives and labels sparse previews uncalibrated')
