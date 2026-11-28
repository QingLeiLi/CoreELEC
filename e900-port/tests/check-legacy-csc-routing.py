#!/usr/bin/env python3
"""Execute the five source routing predicates validated by Build293L SDR trial."""
import json,os,re,shutil,subprocess,tempfile
from pathlib import Path
P=Path(__file__).resolve().parents[1]
A=Path(os.environ.get('E900_AUDIT_ROOT',P.parent/'coreelec-audit'))
FILE='drivers/amlogic/media/enhancement/amvecm/amcsc.c'
PATCH='0044-gxlx2-legacy-sdr-csc-routing.patch'

def function(s,name):
    m=re.search(r'^static (?:void|int) '+name+r'\([^;]*?\)\s*\{',s,re.M);assert m,name
    a=s.index('{',m.start());b=a+1;depth=1
    while depth:depth+=(s[b]=='{')-(s[b]=='}');b+=1
    return s[a:b]

def condition(s,start):
    a=s.index('(',start);b=a+1;depth=1
    while depth:depth+=(s[b]=='(')-(s[b]==')');b+=1
    return s[a+1:b-1]

def routes(s):
    f=function(s,'vpp_matrix_update');bypass=function(s,'bypass_hdr_process')
    support=condition(f,f.index('if (!cpu_after_eq(MESON_CPU_MAJOR_ID_G12A)'))
    # Anchor each block by its operation; do not accidentally test a different
    # G12 conditional in the same long function.
    def before(anchor):
        end=f.index(anchor)
        a=f.rfind('if (cpu_after_eq(MESON_CPU_MAJOR_ID_G12A)',0,end)
        return condition(f,a)
    packet=before('hdmi_packet_process(signal_change_flag')
    post=before('e900_csc_last_branch = 1;')
    bypass_route=condition(bypass,bypass.index('if (get_cpu_type() >= MESON_CPU_MAJOR_ID_G12A'))
    # hdr_policy_process is under the FIRST top-level G12 brace, not the
    # format-specific histogram/update branches.
    p=f.index('enum vd_path_e oth_path')
    policy=condition(f,f.rfind('if (cpu_after_eq(MESON_CPU_MAJOR_ID_G12A)',0,p))
    return (support,policy,packet,post,bypass_route)

with tempfile.TemporaryDirectory(prefix='e900-legacy-csc-') as directory:
    root=Path(directory)
    for r in json.loads((P/'tests/source-fixtures.json').read_text()):
        if r['repo']=='CoreELEC/linux-amlogic':
            dst=root/r['path'];dst.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(A/'sources'/r['path'].replace('/','__'),dst)
    for patch in sorted((P/'patches/linux').glob('*.patch')):
        if patch.name==PATCH:old=(root/FILE).read_text()
        subprocess.run(['git','apply',str(patch)],cwd=root,check=True)
        if patch.name==PATCH:break  # Isolate the original five-selector regression.
    new=(root/FILE).read_text()
    # This formal patch is EXACTLY the successful binary trial's source model.
    candidate=(P/'candidates/0045-gxlx2-legacy-sdr-csc-route.patch').read_text()
    active=(P/'patches/linux'/PATCH).read_text()
    assert candidate[candidate.index('--- a/'):]==active[active.index('--- a/'):]
    # Remove only the five approved predicate additions: all other policy and
    # the legacy/G12 register-writing bodies must remain byte-identical.
    stripped=new.replace('if (get_cpu_type() >= MESON_CPU_MAJOR_ID_G12A &&\n\t    !is_meson_gxlx2_cpu()) {','if (get_cpu_type() >= MESON_CPU_MAJOR_ID_G12A) {',1)
    stripped=stripped.replace('if (!cpu_after_eq(MESON_CPU_MAJOR_ID_G12A) ||\n\t    is_meson_gxlx2_cpu())','if (!cpu_after_eq(MESON_CPU_MAJOR_ID_G12A))',1)
    stripped=stripped.replace('if (cpu_after_eq(MESON_CPU_MAJOR_ID_G12A) &&\n\t    !is_meson_gxlx2_cpu()) {','if (cpu_after_eq(MESON_CPU_MAJOR_ID_G12A)) {',2)
    stripped=stripped.replace('if (cpu_after_eq(MESON_CPU_MAJOR_ID_G12A) &&\n\t\t!is_meson_gxlx2_cpu() &&','if (cpu_after_eq(MESON_CPU_MAJOR_ID_G12A) &&',1)
    assert stripped==old,'Unexpected helper/policy modifications'
    code='''#include <assert.h>
#include <stdbool.h>
#define MESON_CPU_MAJOR_ID_G12A 0x28
#define MESON_CPU_MAJOR_ID_TL1 0x2e
static unsigned cpu;
static bool cpu_after_eq(unsigned n){return cpu>=n;}
static unsigned get_cpu_type(void){return cpu;}
static bool is_meson_gxlx2_cpu(void){return cpu==0x2a;}
'''
    for label,src in (('baseline',old),('fixed',new)):
        code+='static void '+label+'(int route[5]){\n'
        for i,expr in enumerate(routes(src)):code+=f'route[{i}]=({expr});\n'
        code+='}\n'
    code+='''int main(void){
 for(cpu=0;cpu<0x80;cpu++){
  int old[5],now[5];baseline(old);fixed(now);
  if(cpu==0x2a){assert(now[0]);for(int i=1;i<5;i++)assert(!now[i]);}
  else{for(int i=0;i<5;i++)assert(old[i]==now[i]);}
 }
 return 0;
}
'''
    (root/'test.c').write_text(code)
    for std in ('gnu89','gnu99'):
        # The harness uses C99 loop declarations; kernel predicates themselves
        # also compile in the gnu89 wrapper below.
        wrapped=code.replace('for(int i=1;i<5;i++)','for(i=1;i<5;i++)').replace('for(int i=0;i<5;i++)','for(i=0;i<5;i++)').replace('int old[5],now[5];','int old[5],now[5],i;')
        (root/'test.c').write_text(wrapped)
        subprocess.run([shutil.which('clang') or 'cc','-std='+std,'-Wall','-Wextra','-Werror',str(root/'test.c'),'-o',str(root/'test')],check=True)
        subprocess.run([str(root/'test')],check=True)
print('PASS: five actual CSC predicates select legacy only on GXLX2; other CPU IDs 0..127 unchanged; all helper/write bodies byte-identical; source matches successful 293L trial')
print('PENDING: source-built ARM, repeated playback/output edge and non-SDR format validation')
