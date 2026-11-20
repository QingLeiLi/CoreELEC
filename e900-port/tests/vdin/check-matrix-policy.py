"""Execute real matrix/HDR functions against the pinned upstream policy."""
from pathlib import Path
import os,re,shutil,subprocess,tempfile

LINUX=Path(os.environ['E900_CAPTURE_LINUX_ROOT'])
AUDIT=Path(os.environ['E900_AUDIT_ROOT'])
relative='drivers/amlogic/media/vin/tvin/vdin/vdin_ctl.c'
upstream=(AUDIT/'sources'/relative.replace('/','__')).read_text()
patched=(LINUX/relative).read_text()

def function(source,name):
    match=re.search(r'^void '+name+r'\([^;]*?\)\s*\{',source,re.M)
    assert match,name
    pos=source.index('{',match.start())+1
    depth=1
    while depth:
        depth+=(source[pos]=='{')-(source[pos]=='}')
        pos+=1
    return source[match.start():pos]+'\n'

names=['vdin_set_hdr','vdin_set_matrix']
real='\n'.join(function(patched,n) for n in names)
old='\n'.join(function(upstream,n) for n in names)
for name in names:
    old=old.replace(name+'(', 'upstream_'+name+'(')
tokens=sorted(set(re.findall(r'\b[A-Z][A-Z0-9_]+\b',real+old)))
defines='\n'.join('#define %s %d'%(name,i+100) for i,name in enumerate(tokens)
                  if name not in ['MESON_CPU_MAJOR_ID_G12A','CONFIG_AMLOGIC_MEDIA_ENHANCEMENT_DOLBYVISION'])
preamble=r'''
#include <assert.h>
#include <stdbool.h>
#include <string.h>
#include <stdio.h>
#define MESON_CPU_MAJOR_ID_G12A 0x28
#define pr_info(...) ((void)0)
#define pr_err(...) ((void)0)
enum vd_format_e { FORMAT_HDR10=SIGNAL_HDR10,FORMAT_HDR10PLUS=SIGNAL_HDR10PLUS,
 FORMAT_SDR=SIGNAL_SDR,FORMAT_HLG=SIGNAL_HLG,FORMAT_DOVI=SIGNAL_DOVI };
enum vdin_format_convert_e { CONVERT_DUMMY };
enum vdin_matrix_sel_e { MATRIX_DUMMY };
struct vdin_dev_s {
 unsigned int index,addr_offset,csc_idx,format_convert,color_range_mode,matrix_pattern_mode;
 unsigned int vd1_fmt,tx_fmt;
 void *fmt_info_p;
 struct { unsigned int port; struct { unsigned int fmt; } info; } parm;
 struct { unsigned int color_fmt_range,vdin_hdr_flag; } prop;
 struct { unsigned int dv_flag; } dv;
 struct { unsigned int hw_ver; } *dtdata;
};
static unsigned int cpu,rgb_info_enable,rgb_info_x,rgb_info_y;
struct event { unsigned int v[12]; };
static struct event events[32];
static unsigned int count;
static void record(unsigned int a,unsigned int b,unsigned int c,unsigned int d,
 unsigned int e,unsigned int f,unsigned int g,unsigned int h,unsigned int i,unsigned int j)
{
 assert(count<32);
 events[count++]=(struct event){{a,b,c,d,e,f,g,h,i,j,0,0}};
}
static bool is_meson_gxlx2_cpu(void) { return cpu==0x2a; }
static bool is_meson_g12a_cpu(void) { return cpu==0x28; }
static bool is_meson_g12b_cpu(void) { return cpu==0x29; }
static bool is_meson_sm1_cpu(void) { return cpu==0x2b; }
static bool is_meson_tm2_cpu(void) { return cpu==0x2f; }
static bool cpu_after_eq(unsigned int value) { return cpu>=value; }
#ifdef CONFIG_AMLOGIC_MEDIA_ENHANCEMENT_DOLBYVISION
static bool vdin_is_dolby_signal_in(struct vdin_dev_s *dev)
{ return dev->matrix_pattern_mode!=0; }
#endif
static void hdr_set(unsigned int module,unsigned int mode)
{ record(1,module,mode,0,0,0,0,0,0,0); }
static void wr_bits(unsigned int a,unsigned int b,unsigned int c,unsigned int d,unsigned int e)
{ record(2,a,b,c,d,e,0,0,0,0); }
static unsigned int vdin_set_color_matrix(unsigned int sel,unsigned int offset,void *fmt,
 unsigned int convert,unsigned int port,unsigned int range,unsigned int hdr,unsigned int color)
{
 (void)fmt;
 record(3,sel,offset,convert,port,range,hdr,color,0,0);
 return sel;
}
static enum vdin_format_convert_e vdin_get_format_convert_matrix0(struct vdin_dev_s *dev)
{ (void)dev; return (enum vdin_format_convert_e)7; }
static enum vdin_format_convert_e vdin_get_format_convert_matrix1(struct vdin_dev_s *dev)
{ (void)dev; return (enum vdin_format_convert_e)9; }
static void vdin_set_matrix_color(unsigned int index,unsigned int mode)
{ record(4,index,mode,0,0,0,0,0,0,0); }
'''
main=r'''
int main(void) {
 unsigned int cpus[]={0x1f,0x21,0x22,0x23,0x24,0x25,0x28,0x29,0x2a,0x2b,0x2f,0x32};
 unsigned int formats[]={SIGNAL_HDR10,SIGNAL_HDR10PLUS,SIGNAL_SDR,SIGNAL_HLG,SIGNAL_DOVI,999};
 unsigned int ports[]={TVIN_PORT_VIU1_WB0_VD1,TVIN_PORT_VIU1_WB0_VPP,999};
 unsigned int c,r,f,p,index,pattern,hw,cases=0,i,old_count;
 struct event saved[32];
 struct { unsigned int hw_ver; } hardware;
 struct vdin_dev_s dev;
 for(c=0;c<sizeof(cpus)/sizeof(cpus[0]);c++)
 for(r=0;r<2;r++) for(f=0;f<6;f++) for(p=0;p<3;p++)
 for(index=0;index<2;index++) for(pattern=0;pattern<2;pattern++) for(hw=0;hw<2;hw++) {
  memset(&dev,0,sizeof(dev));hardware.hw_ver=hw?VDIN_HW_SC2:0;
  dev.dtdata=(void *)&hardware;dev.index=index;dev.addr_offset=index?0x80:0;
  dev.tx_fmt=formats[f];dev.vd1_fmt=formats[(f+1)%6];dev.parm.port=ports[p];
  dev.format_convert=3;dev.color_range_mode=1;dev.matrix_pattern_mode=pattern;
  dev.prop.color_fmt_range=2;dev.prop.vdin_hdr_flag=1;
  cpu=cpus[c];rgb_info_enable=r;rgb_info_x=17;rgb_info_y=19;
  count=0;upstream_vdin_set_matrix(&dev);old_count=count;memcpy(saved,events,sizeof(events));
  count=0;vdin_set_matrix(&dev);
  if(cpu!=0x2a) {
   assert(count==old_count);assert(!memcmp(saved,events,count*sizeof(events[0])));
  } else {
   unsigned int matrices=0;
   for(i=0;i<count;i++) {
    assert(events[i].v[0]!=1);
    if(events[i].v[0]==3) {
     assert(events[i].v[1]==(r && matrices==0?VDIN_SEL_MATRIX1:
       (r && hw?VDIN_SEL_MATRIXHDR:VDIN_SEL_MATRIX0)));
     matrices++;
    }
   }
   assert(matrices==(r?2:1));
   count=0;vdin_set_hdr(&dev);assert(count==0);
  }
  cases++;
 }
 printf("PASS: %u actual matrix/HDR cases; non-GXLX2 traces match upstream, GXLX2 skips G12 HDR and uses matrix0 in capture mode\n",cases);
 return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='e900-vdin-matrix-') as t:
    root=Path(t);source=root/'test.c'
    source.write_text(defines+'\n'+preamble+'\n'+old+'\n'+real+'\n'+main)
    compiler=shutil.which('clang') or 'cc'
    for dolby in [False,True]:
        flags=['-DCONFIG_AMLOGIC_MEDIA_ENHANCEMENT_DOLBYVISION=1'] if dolby else []
        subprocess.run([compiler,'-std=gnu89','-Wall','-Werror',*flags,str(source),'-o',str(root/'test')],check=True)
        subprocess.run([str(root/'test')],check=True)
    print('PASS: matrix/HDR policies exercised with Dolby support both disabled and enabled')
