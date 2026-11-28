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
 code+='int main(void){unsigned mode,frame,output;for(cpu=0;cpu<128;cpu++){for(mode=0;mode<3;mode++)for(frame=0;frame<2;frame++)for(output=0;output<2;output++){(void)mode;(void)frame;(void)output;\n'
 for before,after in pairs:
  code+=f'if(cpu==0x2a)assert(({after})=={int(before.startswith("!"))});else assert(({before})==({after}));\n'
 code+='writes=0;histogram_init();\n'
 for name in writers:code+=f'writer_{name}(0x123);\n'
 code+=f'assert(writes==(cpu==0x2a?0:{len(writers)+1}));'+'}}return 0;}\n'
 c=r/'test.c';c.write_text(code)
 for std in ('gnu89','gnu99'):
  subprocess.run([shutil.which('clang') or 'cc','-std='+std,'-Wall','-Wextra','-Werror','-Wdeclaration-after-statement',str(c),'-o',str(r/'test')],check=True)
  subprocess.run([str(r/'test')],check=True)
print('PASS: 49 actual CSC/PQ/CM/VADJ gates select legacy on GXLX2 for all output modes; other CPUs 0..127 unchanged')
print('PASS: 14 HDR2 entry guards plus histogram init reject GXLX2 before side effects; remaining write bodies unchanged')
print('PENDING: full ARM build, LCD/non-HDMI hardware, SDR regression and HDR10/HLG color validation')
