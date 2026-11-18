#!/usr/bin/env python3
"""Compile patched registration and VLD mask logic with scoped hardware stubs."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

PORT=Path(__file__).resolve().parents[1]
AUDIT=Path(os.environ.get('E900_AUDIT_ROOT',PORT.parent/'coreelec-audit'))
FILES={'linux':'drivers/amlogic/media/common/arch/registers/register_ops_m8.c',
       'media':'drivers/frame_provider/decoder/utils/vdec.c'}
with tempfile.TemporaryDirectory(prefix='e900-media-buses-') as directory:
    root=Path(directory)
    for package,path in FILES.items():
        dest=root/package/path;dest.parent.mkdir(parents=True)
        shutil.copy2(AUDIT/'sources'/path.replace('/','__'),dest)
        patch='linux/0006-gxlx2-direct-media-register-buses.patch' if package=='linux' else 'media/0003-gxlx2-vld-dmc-channel.patch'
        subprocess.run(['git','apply',str(PORT/'patches'/patch)],cwd=root/package,check=True)
    source=(root/'linux'/FILES['linux']).read_text()
    source=re.sub(r'^#include.*\n','',source,flags=re.M)
    cpuh=(AUDIT/'sources/include__linux__amlogic__cpu_version.h').read_text()
    cpuh+=(AUDIT/'sources/include__linux__amlogic__media__old_cpu_version.h').read_text()
    defines='\n'.join(re.findall(r'^#define MESON_CPU_MAJOR_ID_\w+\s+0x\w+',cpuh,re.M))
    buses=['DOS','AO','HHI','C','VC','DEMUX','PARSER','VLD','AIU','VDEC','VDEC2','HCODEC','HEVC','VPP','DMC','RESET','EFUSE']
    harness='''#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdlib.h>
#define __init
#define __initdata
#define postcore_initcall(x) static int (*early_init)(void)=x
#define late_initcall_sync(x) static int (*late_init)(void)=x
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define MESON_CPU_MAJOR_ID_GXLX2 0x2a
struct chip_register_ops { int bus_type,ext_offset; int (*read)(unsigned); void (*write)(unsigned,unsigned); int r_cnt,w_cnt; };
static int cpu,calls,count,forced_error;
static struct chip_register_ops result[17];
static int get_cpu_type(void) { return cpu; }
static bool is_meson_gxlx2_cpu(void) { return cpu==0x2a; }
static int register_reg_ops_per_cpu(int id,struct chip_register_ops *ops,int n) {
 if(id!=cpu) return 0;
 if(forced_error) return forced_error;
 calls++;count+=n;for(int i=0;i<n;i++)result[ops[i].bus_type]=ops[i];return 0;
}
static int register_reg_ops_mgr(int *ids,struct chip_register_ops *ops,int n) {
 for(int i=0;ids[i];i++)register_reg_ops_per_cpu(ids[i],ops,n);return 0;
}
#define register_reg_ex_ops_mgr register_reg_ops_mgr
'''+defines+'\nenum { '+','.join('IO_'+b+'_BUS' for b in buses)+' };\n'
    for name in sorted(set(re.findall(r'codecio_(?:read|write)_\w+',source))):
        harness+=('static int '+name+'(unsigned r) { return (int)r; }\n') if '_read_' in name else ('static void '+name+'(unsigned r,unsigned v) { (void)r;(void)v; }\n')
    harness+=source+r'''
int main(int argc,char **argv) {
 assert(argc==2);cpu=(int)strtol(argv[1],NULL,0);assert(early_init()==0);
 if(cpu==0x2a) {
  assert(calls==0 && count==0); /* No early GXLX2 interface publication. */
  assert(late_init()==0);
  assert(calls==1 && count==7);
  int expected[]={IO_DOS_BUS,IO_AO_BUS,IO_HHI_BUS,IO_C_BUS,IO_VC_BUS,IO_VPP_BUS,IO_DMC_BUS};
  for(int i=0;i<7;i++){int b=expected[i];assert(result[b].read && result[b].write);assert(result[b].ext_offset==(b==IO_HHI_BUS?-0x1000:0));}
  assert(!result[IO_PARSER_BUS].read && !result[IO_AIU_BUS].read && !result[IO_DEMUX_BUS].read && !result[IO_RESET_BUS].read);
  assert(result[IO_HHI_BUS].read==codecio_read_hiubus);
  assert(result[IO_DMC_BUS].read==codecio_read_dmcbus);
  forced_error=-12;assert(late_init()==-12); /* Preserve allocation failure. */
 } else if(cpu==0x26) {
  assert(late_init()==0);
  assert(calls==0 && count==0); /* Existing absent registration is preserved. */
 } else {
  int before=calls;assert(late_init()==0 && calls==before);
  assert(calls==2 && count==13);
  assert(result[IO_PARSER_BUS].read && result[IO_AIU_BUS].read);
  assert(result[IO_PARSER_BUS].ext_offset==(cpu>MESON_CPU_MAJOR_ID_TXL && cpu!=MESON_CPU_MAJOR_ID_GXLX?0xf00:0));
 }
 return 0;
}
'''
    c=root/'buses.c';c.write_text(harness)
    compiler=shutil.which('clang') or shutil.which('cc')
    subprocess.run([compiler,'-std=c99','-Wall','-Werror',str(c),'-o',str(root/'buses')],check=True)
    for cpu in ['0x2a','0x21','0x24','0x26','0x28']:
        subprocess.run([str(root/'buses'),cpu],check=True)
    source=(root/'media'/FILES['media']).read_text()
    start=source.index('static unsigned int vdec_vld_dmc_mask(');end=source.index('\n}',start)+2
    assert source.count('vdec_vld_dmc_mask(')==4
    c.write_text('''#include <assert.h>
#define AM_MESON_CPU_MAJOR_ID_G12A 0x28
#define AM_MESON_CPU_MAJOR_ID_GXLX2 0x2a
static unsigned int cpu;
static unsigned int get_cpu_major_id(void) {return cpu;}
'''+source[start:end]+'''
int main(void) {
 for(cpu=0;cpu<0x40;cpu++)assert(vdec_vld_dmc_mask()==(1U<<(cpu>=0x28 && cpu!=0x2a?21:13)));
 return 0;
}
''')
    subprocess.run([compiler,'-std=c99','-Wall','-Werror',str(c),'-o',str(root/'mask')],check=True)
    subprocess.run([str(root/'mask')],check=True)
print('PASS: GXLX2 publishes no early buses, installs seven at late sync init and propagates failures; other SoC paths preserved')
print('PASS: all three VLD DMC paths share bit13 for GXLX2; other CPU masks preserved')
