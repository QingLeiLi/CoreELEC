#!/usr/bin/env python3
"""Exercise full legacy generation gates and reject every guarded HDR2 writer.

Tests production predicates for all CPU IDs, independently of output mode.
Does not validate silicon register layout, tone-map colors or a full ARM build.
"""
import hashlib,json,os,re,shutil,subprocess,tempfile
from pathlib import Path
P=Path(__file__).resolve().parents[1]
A=Path(os.environ.get('E900_AUDIT_ROOT',P.parent/'coreelec-audit'))
D='drivers/amlogic/media/enhancement/amvecm/'
PATCH='0045-gxlx2-all-output-legacy-csc-pq.patch'
GUARD='\t/* GXLX2 uses legacy CSC/LUTs on every output; never program HDR2. */\n\tif (is_meson_gxlx2_cpu())\n\t\treturn'
writers={'eo_clip_proc':'','set_hdr_matrix':'','set_eotf_lut':'','set_ootf_lut':'','set_oetf_lut':'','set_c_gain':'','set_hist':'','get_hist':'','hdr_hist_config':'','hdr_func':'hdr_process_select','hdr10p_func':'hdr_process_select','hdr10p_ebzcurve_update':'0','hdr10_tm_update':'0','cuva_hdr_update':'0'}

def body(s,name):
 m=re.search(r'^[^\n]*\b'+name+r'\([^;]*?\)\s*\{',s,re.M);assert m,name
 a=s.index('{',m.start());b=a+1;depth=1
 while depth:depth+=(s[b]=='{')-(s[b]=='}');b+=1
 return s[a+1:b-1]

with tempfile.TemporaryDirectory(prefix='e900-all-legacy-') as td:
 r=Path(td)
 for row in json.loads((P/'tests/source-fixtures.json').read_text()):
  if row['repo']=='CoreELEC/linux-amlogic':
   f=A/'sources'/row['path'].replace('/','__');data=f.read_bytes()
   assert hashlib.sha256(data).hexdigest()==row['sha256'],row['path']
   d=r/row['path'];d.parent.mkdir(parents=True,exist_ok=True);d.write_bytes(data)
 old={}
 for p in sorted((P/'patches/linux').glob('*.patch')):
  if p.name==PATCH:old={n:(r/D/n).read_text() for n in ('amcsc.c','amvecm.c','amve.c','amcm.c','set_hdr2_v0.c')}
  subprocess.run(['git','apply',str(p)],cwd=r,check=True)
 assert old
 code='''#include <assert.h>
#include <stdbool.h>
#define MESON_CPU_MAJOR_ID_G12A 0x28
static unsigned cpu, writes;
static bool is_meson_gxlx2_cpu(void){return cpu==0x2a;}
static unsigned get_cpu_type(void){return cpu;}
static bool cpu_after_eq(unsigned n){return cpu>=n;}
'''
 pairs=[]
 for n,expected in [('amcsc.c',13),('amvecm.c',24),('amve.c',8),('amcm.c',4)]:
  s=(r/D/n).read_text()
  # These are the ACTUAL newly added predicates, not a hand-written model.
  pat=r'\((!?cpu_after_eq\(MESON_CPU_MAJOR_ID_G12A\)|get_cpu_type\(\)\s*>=\s*MESON_CPU_MAJOR_ID_G12A) (&& !|\|\| )is_meson_gxlx2_cpu\(\)\)'
  matches=list(re.finditer(pat,s));assert len(matches)==expected,(n,len(matches))
  pairs.extend((m[1],m[0]) for m in matches)
  restored=re.sub(pat,lambda m:m[1],s)
  if '#include <linux/amlogic/cpu_version.h>' not in old[n]:restored=restored.replace('#include <linux/amlogic/cpu_version.h>\n','',1)
  if n=='amvecm.c':
   guard='\t/* No HDR2 histogram writes on the all-output legacy path. */\n\tif (is_meson_gxlx2_cpu())\n\t\treturn;\n'
   assert guard in body(s,'hdr_hist_config_int');restored=restored.replace(guard+'\n','',1)
   # Actual guard plus a mock hardware side effect; no output-mode condition.
   code+='static void histogram_init(void){\n'+guard+'writes++;}\n'
  assert restored==old[n],n+' has unintended changes outside predicates/guards/includes'
 hdr=(r/D/'set_hdr2_v0.c').read_text();restored=hdr
 for name,ret in writers.items():
  f=body(hdr,name);guard=GUARD+(' '+ret if ret else '')+';\n\n'
  assert f.count(guard)==1,name
  prefix=f[:f.index(guard)]
  # Guard must precede all executable hardware/callback operations. Local
  # declarations/constant initializers may precede it for kernel gnu89 style.
  assert not re.search(r'\b(?:READ_|WRITE_|VSYNC_|rdma_|memset|pr_csc|if\s*\()',prefix),name
  restored=restored.replace(guard,'',1)
  code+=f'static {"unsigned" if ret else "void"} writer_{name}(unsigned hdr_process_select){{\n(void)hdr_process_select;\n'+guard+'writes++;'+('return hdr_process_select;' if ret else '')+'}\n'
 if '#include <linux/amlogic/cpu_version.h>' not in old['set_hdr2_v0.c']:restored=restored.replace('#include <linux/amlogic/cpu_version.h>\n','',1)
 assert restored==old['set_hdr2_v0.c'],'unexpected changes to HDR2 write sequences'
 code+='int main(void){for(cpu=0;cpu<128;cpu++){\n'
 for before,after in pairs:
  code+=f'if(cpu==0x2a)assert(({after})=={int(before.startswith("!"))});else assert(({before})==({after}));\n'
 code+='writes=0;histogram_init();\n'
 for name in writers:code+=f'writer_{name}(0x123);\n'
 code+=f'assert(writes==(cpu==0x2a?0:{len(writers)+1}));'+'}return 0;}\n'
 c=r/'test.c';c.write_text(code)
 for std in ('gnu89','gnu99'):
  subprocess.run([shutil.which('clang') or 'cc','-std='+std,'-Wall','-Wextra','-Werror','-Wdeclaration-after-statement',str(c),'-o',str(r/'test')],check=True)
  subprocess.run([str(r/'test')],check=True)

 # Execute the REAL two output-dependent tails, not loops over unused modes.
 def output_tail(src,name):
  f=body(src,name)
  end=f.index('\n\tif (cur_hdr_process_mode') if name=='video_process' else f.index('\n\t/* eye protection mode */')
  matches=list(re.finditer(r'\n\tif \([^\n]*get_cpu_type\(\) >= MESON_CPU_MAJOR_ID_G12A',f[:end]))
  assert matches,name
  a=matches[-1].start();start=f.index('{',a);b=start+1;depth=1
  while depth:depth+=(f[b]=='{')-(f[b]=='}');b+=1
  return f[a:b]
 actual=(r/D/'amcsc.c').read_text()
 outputs=r"""
#include <assert.h>
#include <stdbool.h>
#include <string.h>
#define MESON_CPU_MAJOR_ID_G12A 0x28
#define VIDTYPE_RGB_444 1
#define HDRTYPE_SDR 0
#define VMODE_LCD 0
#define VMODE_HDMI 1
#define VMODE_DUMMY_ENCP 2
#define POST2_MTX 1
#define MATRIX_NULL 0
#define MTX_OFF 0
#define MTX_ON 1
#define VPP_VADJ1_MISC 11
#define VPP_VADJ2_MISC 12
#define VPP_POST2_MATRIX_EN_CTRL 13
#define VPP_LUT3D_CTRL 14
#define SIG_RANGE_CHG 1
#define SIG_BS_CHG 2
/* Only selectors/arguments are mocked; the actual branch bodies are intact.
 * A recorded API invocation is not a hardware write/completion assertion. */
enum mtx_csc_e { MATRIX_YUV709F_RGB=20, MATRIX_YUV709_RGB=21,
 MATRIX_YUV709F_YUV709=22 };
struct vframe_s {unsigned type;};
struct vinfo_s {unsigned mode;};
static struct vframe_s frame;
static struct vframe_s *vf;
static struct vinfo_s info,*vinfo=&info;
static unsigned cpu,source_type[2],source_format[2],vd_path,csc_type;
static unsigned signal_change_flag,bs_3dlut_en,bs_proc_en;
static unsigned calls[64][5],count;
static unsigned get_cpu_type(void){return cpu;}
static bool is_meson_gxlx2_cpu(void){return cpu==0x2a;}
static bool vinfo_lcd_support(void){return info.mode==VMODE_LCD || info.mode==VMODE_DUMMY_ENCP;}
static void note(unsigned op,unsigned a,unsigned b,unsigned c,unsigned d){
 assert(count<64);calls[count][0]=op;calls[count][1]=a;calls[count][2]=b;
 calls[count][3]=c;calls[count++][4]=d;
}
#define WRITE_VPP_REG_BITS(r,v,s,n) note(1,r,v,s,n)
#define mtx_setting(s,c,on) note(2,s,c,on,0)
#define mtx_init(s,c,on) note(3,s,c,on,0)
#define vpp_enable_lut3d(a,b) note(4,a,b,0,0)
"""
 for label,src in [('baseline',old['amcsc.c']),('candidate',actual)]:
  outputs+='static void '+label+'(void){\n'+output_tail(src,'video_process')+'\n'+output_tail(src,'vpp_matrix_update')+'\n}\n'
 outputs+=r"""
int main(void){
 unsigned mode,frame_kind,format,flags,lut,path;
 for(cpu=0;cpu<128;cpu++)for(mode=0;mode<3;mode++)
 for(frame_kind=0;frame_kind<3;frame_kind++)for(format=0;format<2;format++)
 for(flags=0;flags<4;flags++)for(lut=0;lut<4;lut++)for(path=0;path<2;path++){
  unsigned saved[64][5],expected;
  info.mode=mode;frame.type=frame_kind==2?VIDTYPE_RGB_444:0;
  vf=frame_kind?&frame:0;vd_path=path;csc_type=23;
  source_type[path]=source_format[path]=format;
  signal_change_flag=flags;bs_3dlut_en=lut&1;bs_proc_en=(lut>>1)&1;
  count=0;baseline();expected=count;memcpy(saved,calls,sizeof saved);
  count=0;candidate();
  if(cpu==0x2a)assert(count==0);
  else{assert(count==expected);assert(!memcmp(calls,saved,count*sizeof calls[0]));}
 }
 return 0;
}
"""
 c.write_text(outputs)
 for std in ('gnu89','gnu99'):
  subprocess.run([shutil.which('clang') or 'cc','-std='+std,'-Wall','-Wextra','-Werror','-Wdeclaration-after-statement',str(c),'-o',str(r/'outputs')],check=True)
  subprocess.run([str(r/'outputs')],check=True)
print('PASS: real video_process/matrix_update output tails: LCD/HDMI/dummy ENCP, no/YUV/RGB frame, SDR/HDR, VD1/VD2, range/BS and 3DLUT states; GXLX2 skips all G12 tail calls; other CPUs keep the exact API call sequence')
print('PASS: 49 actual CSC/PQ/CM/VADJ predicates select legacy on GXLX2; other CPUs 0..127 unchanged')
print('PASS: 14 HDR2 entry guards plus histogram init reject GXLX2 before side effects; remaining write bodies unchanged')
print('PENDING: full ARM build, LCD/non-HDMI hardware, SDR regression and HDR10/HLG color validation')
