"""Validate builtin-only dependencies and GNU89 TVAFE provider linkage."""
from pathlib import Path
import os,re,subprocess,tempfile,shutil
LINUX=Path(os.environ['E900_CAPTURE_LINUX_ROOT']);PORT=Path(__file__).resolve().parents[2]
providers={
 '__irq_set_affinity':'kernel/irq/manage.c',
 'irq_can_set_affinity':'kernel/irq/manage.c',
 'vlock_get_vlock_flag':'drivers/amlogic/media/enhancement/amvecm/vlock.c',
 'vlock_get_phlock_flag':'drivers/amlogic/media/enhancement/amvecm/vlock.c',
 'switch_vpu_mem_pd_vmod':'drivers/amlogic/media/common/vpu/vpu.c',
 'switch_vpu_clk_gate_vmod':'drivers/amlogic/media/common/vpu/vpu.c',
 'is_vmalloc_or_module_addr':'mm/vmalloc.c',
 '__close_fd':'fs/file.c',
 'extcon_dev_allocate':'drivers/extcon/extcon.c',
 'IS_TVAFE_SRC':'drivers/amlogic/media/vin/tvin/tvin_global.c',
 'IS_TVAFE_ATV_SRC':'drivers/amlogic/media/vin/tvin/tvin_global.c',
}
for symbol,path in providers.items():
 text=(LINUX/path).read_text()
 assert re.search(r'^.*\b'+re.escape(symbol)+r'\([^;]*?\)\s*\{',text,re.M),symbol
 assert not re.search(r'EXPORT_SYMBOL(?:_GPL)?\s*\(\s*'+re.escape(symbol)+r'\s*\)',text),symbol
config=Path(os.environ['E900_CAPTURE_CONFIG_BASE']).read_text().splitlines()
for enabled in ['CONFIG_SMP=y','CONFIG_MODULES=y','CONFIG_AMLOGIC_VPU=y','CONFIG_AMLOGIC_MEDIA_ENHANCEMENT_VECM=y','CONFIG_EXTCON=y']:assert enabled in config,enabled
assert 'am_vecm-objs += vlock.o' in (LINUX/'drivers/amlogic/media/enhancement/amvecm/Makefile').read_text()
assert 'tvin_common-objs += tvin_global.o' in (LINUX/'drivers/amlogic/media/vin/tvin/Makefile').read_text()
assert '-std=gnu89' in (LINUX/'Makefile').read_text()
kconfig=(LINUX/'drivers/amlogic/media/vin/tvin/vdin/Kconfig').read_text()
assert 'depends on VIDEO_V4L2 && HAS_DMA' in kconfig and 'select VIDEOBUF2_DMA_CONTIG' in kconfig
common=(LINUX/'drivers/amlogic/media/vin/tvin/tvin_global.c').read_text()
functions=[]
for name in ['IS_TVAFE_SRC','IS_TVAFE_ATV_SRC']:
 m=re.search(r'^inline bool '+name+r'\([^;]*?\)\s*\{',common,re.M);assert m
 i=common.index('{',m.start())+1;depth=1
 while depth:
  depth+=(common[i]=='{')-(common[i]=='}');i+=1
 functions.append(common[m.start():i]+'\n')
h=(LINUX/'include/linux/amlogic/media/frame_provider/tvin/tvin.h').read_text();start=h.index('enum tvin_port_e {');enum=h[start:h.index('};',start)+2]
preamble='#include <stdbool.h>\n'+enum+'\n'
consumer=preamble+'''#include <assert.h>
extern bool IS_TVAFE_SRC(enum tvin_port_e port);
extern bool IS_TVAFE_ATV_SRC(enum tvin_port_e port);
int main(void) {
 unsigned int p;
 for (p=0;p<=0x20010;p++) {
  assert(IS_TVAFE_SRC(p)==(p>=TVIN_PORT_CVBS0 && p<=TVIN_PORT_CVBS3));
  assert(IS_TVAFE_ATV_SRC(p)==(p==TVIN_PORT_CVBS3));
 }
 return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='e900-builtin-link-') as t:
 root=Path(t);(root/'provider.c').write_text(preamble+''.join(functions));(root/'consumer.c').write_text(consumer)
 compiler=shutil.which('clang') or 'cc'
 for name in ['provider','consumer']:
  subprocess.run([compiler,'-std=gnu89','-fno-inline','-Wall','-Werror','-c',str(root/(name+'.c')),'-o',str(root/(name+'.o'))],check=True)
 subprocess.run([compiler,str(root/'provider.o'),str(root/'consumer.o'),'-o',str(root/'test')],check=True)
 subprocess.run([str(root/'test')],check=True)
drv=(LINUX/'drivers/amlogic/media/vin/tvin/vdin/vdin_drv.c').read_text()
assert 'module_param(gxlx2_capture, bool, 0644);' in drv and 'static bool gxlx2_capture;' in drv
m=re.search(r'^static int vdin_drv_probe\([^;]*?\)\s*\{',drv,re.M);assert m
probe=drv[m.start():drv.index('/*got the dt match data*/',m.start())]
assert probe.index('!gxlx2_capture')<probe.index('kzalloc')<probe.index('rdma_register')
script=(PORT/'scripts/e900-start-capture.sh').read_text()
assert 'printf \'1\\n\' > "$parameter"' in script and '/sys/bus/platform/drivers_probe' in script
assert script.index('> "$parameter"')<script.index('> /sys/bus/platform/drivers_probe')
print('PASS: all 11 MODPOST dependencies have builtin providers; real GNU89 TVAFE helpers link across translation units; late runtime probe gate remains default-off.')
