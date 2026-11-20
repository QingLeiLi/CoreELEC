from pathlib import Path
import os
import ast,re,tempfile,subprocess,shutil,json
H=Path(os.environ["E900_CAPTURE_TEST_ROOT"]);P=Path(__file__).resolve().parent/"models"
def literal(path,name):
 for n in ast.parse(path.read_text()).body:
  if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in n.targets):return ast.literal_eval(n.value)
 raise AssertionError(name)
def fn(src,name):
 m=re.search(r'^(?:static )?(?:int|void) '+name+r'\([^;]*?\)\s*\{',src,re.M);assert m,name
 a=src.index('{',m.start());i=a+1;depth=1
 while depth:
  depth+=(src[i]=='{')-(src[i]=='}');i+=1
 return src[m.start():i]+'\n'
canvas=(H/'patched/drivers/amlogic/media/vin/tvin/vdin/vdin_canvas.c').read_text();drv=(H/'patched/drivers/amlogic/media/vin/tvin/vdin/vdin_drv.c').read_text()
pre=literal(P/'dma.py','pre').replace('bool e900_dma_mapped,','bool e900_capture_pinned,e900_dma_mapped,')
extra=literal(P/'dma.py','extra')+'\nstatic unsigned int refs;\n#define THIS_MODULE ((void *)1)\nstatic void __module_get(void *m){assert(m);refs++;}\n'
init=literal(P/'dma.py','main').split('int main(void) {')[0].replace('cpu=0x2a;events=0;', 'cpu=0x2a;refs=0;events=0;')
main=r'''
int main(void){unsigned int cases=0;
 init();assert(!e900_vdin_dma_map(&dev)&&dev.e900_capture_pinned&&refs==1&&map_live);
 for(unsigned int i=0;i<3;i++){vdin_cma_release(&dev);assert(!frees&&map_live&&dev.cma_mem_alloc&&dev.e900_dma_mapped&&refs==1);cases++;}
 assert(!e900_vdin_dma_sync_frame(&dev,0,true));assert(!e900_vdin_dma_sync_frame(&dev,0,false));cases++;
 init();fail_map=true;assert(e900_vdin_dma_map(&dev)<0&&!refs&&!dev.e900_capture_pinned);vdin_cma_release(&dev);assert(frees==1&&!map_live);cases++;
 init();mapped_address+=0x1000;assert(e900_vdin_dma_map(&dev)<0&&!refs&&!dev.e900_capture_pinned);vdin_cma_release(&dev);assert(frees==1&&!map_live);cases++;
 init();cpu=0x21;assert(!e900_vdin_dma_map(&dev)&&!refs&&!dev.e900_capture_pinned);vdin_cma_release(&dev);assert(frees==1&&!map_live);cases++;
 printf("PASS: %u actual DMA mapping/release cases; successful diagnostic pool is retained, failed mapping and other CPUs free normally.\n",cases);return 0;}
'''
service_pre=literal(P/'start.py','pre').replace('unsigned int matrix_pattern_mode;', 'unsigned int matrix_pattern_mode;bool e900_capture_pinned;')
service_pre=service_pre.replace('#define CONFIG_CMA 1','#define CONFIG_CMA 1\n#define VDIN_WORK_MD_E900_CAPTURE 2').replace('unsigned int matrix_pattern_mode;', 'unsigned int matrix_pattern_mode,work_mode;')
service_main=literal(P/'start.py','main')
service_main=service_main.replace(' printf("PASS: %u actual service-function cases;', ''' init();devs[1].e900_capture_pinned=true;assert(start_tvin_service(1,&param)==-EBUSY&&!locks&&!starts&&!allocations);cases++;
 init();cpu=0x21;devs[1].e900_capture_pinned=true;assert(start_tvin_service(1,&param)==0);free(devs[1].fmt_info_p);cases++;
 printf("PASS: %u actual service-function cases;''')
assert 'vdin_driver.driver.suppress_bind_attrs = true;' in drv
m=drv.index('vdin_driver.driver.suppress_bind_attrs = true;');assert 'if (is_meson_gxlx2_cpu())' in drv[m-60:m]
outputs=[]
with tempfile.TemporaryDirectory(prefix='e900-pin-policy-') as t:
 for name,code in [('dma',pre+extra+''.join(fn(canvas,n) for n in ['e900_vdin_dma_map','e900_vdin_dma_unmap','e900_vdin_dma_sync_frame','vdin_cma_release'])+init+main),('service',service_pre+fn(drv,'start_tvin_service')+service_main)]:
  c=Path(t)/(name+'.c');c.write_text(code);exe=c.with_suffix('')
  subprocess.run([shutil.which('clang') or 'cc','-std=c99','-Wall','-Werror','-Wno-unused-function','-Wno-unused-variable','-fsanitize=address,undefined',str(c),'-o',str(exe)],check=True)
  out=subprocess.check_output([str(exe)],text=True);outputs.append(out.strip());print(out,end='')
(H/'pin-host-checks.json').write_text(json.dumps({'results':outputs,'scope':'Actual final map/release and complete service functions with mocked DMA/module/driver dependencies. Bind-attribute gating inspected statically. Hardware drain is not claimed; diagnostic pool/module stay pinned until reboot.'},indent=2)+'\n')
