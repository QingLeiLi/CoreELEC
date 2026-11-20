from pathlib import Path
import os,re,tempfile,subprocess,shutil
H=Path(os.environ['E900_CAPTURE_TEST_ROOT']);src=(H/'patched/drivers/amlogic/media/vin/tvin/vdin/vdin_drv.c').read_text()
m=re.search(r'^int vdin_vframe_put_and_recycle\([^;]*?\)\s*\{',src,re.M);assert m;a=src.index('{',m.start());i=a+1;depth=1
while depth:
 depth+=(src[i]=='{')-(src[i]=='}');i+=1
fn=src[m.start():i]
assert src.count('devp->work_mode != VDIN_WORK_MD_E900_CAPTURE')==2
pre=r'''
#include <assert.h>
#include <stdio.h>
#include <stddef.h>
#define pr_info(...) ((void)0)
#define VDIN_WORK_MD_NORMAL 0
#define VDIN_WORK_MD_V4L 1
#define VDIN_WORK_MD_E900_CAPTURE 2
#define VFRAME_EVENT_PROVIDER_VFRAME_READY 1
struct vframe_s {unsigned long long ready_clock[2];};struct vf_entry {struct vframe_s vf;};
struct vdin_dev_s {unsigned int frame_cnt,work_mode,puted_frame_cnt;void *vfp;const char *name;};
enum vdin_vf_put_md {VDIN_VF_PUT,VDIN_VF_RECYCLE};
static enum vdin_vf_put_md frame_work_mode=VDIN_VF_PUT;
static unsigned int drop_num,time_en,pool_puts,recycles,notifies,v4calls;static int v4error;
static void receiver_vf_put(struct vframe_s *f,void *p){assert(f&&p);recycles++;}
static struct vf_entry *receiver_vf_get(void *p){(void)p;return NULL;}
static void provider_vf_put(struct vf_entry *f,void *p){assert(f&&p);pool_puts++;}
static int vdin_v4l2_if_isr(struct vdin_dev_s *d,struct vframe_s *f){assert(d&&f);v4calls++;return v4error;}
static unsigned long long sched_clock(void){return 9;}
static void vf_notify_receiver(const char *s,int event,void *p){(void)p;assert(s&&event==1);notifies++;}
'''
main=r'''
int main(void){unsigned int cases=0;for(unsigned int mode=0;mode<3;mode++)for(unsigned int bad=0;bad<2;bad++){
 struct vdin_dev_s d={.frame_cnt=10,.work_mode=mode,.vfp=&d,.name="test"};struct vf_entry f={0};pool_puts=recycles=notifies=v4calls=0;v4error=bad?-1:0;
 int ret=vdin_vframe_put_and_recycle(&d,&f,VDIN_VF_PUT);
 if(mode==VDIN_WORK_MD_V4L){assert(v4calls==1&&!pool_puts&&!notifies&&ret==(bad?-1:0)&&recycles==bad);}
 else assert(pool_puts==1&&!v4calls&&!recycles&&!ret&&notifies==(mode==VDIN_WORK_MD_NORMAL));
 cases++;}
 printf("PASS: %u actual frame-publication cases; capture ring gets frames without a display/V4L2 consumer notification.\n",cases);return 0;}
'''
with tempfile.TemporaryDirectory(prefix='e900-ring-mode-') as t:
 c=Path(t)/'test.c';c.write_text(pre+fn+main);exe=c.with_suffix('')
 subprocess.run([shutil.which('clang') or 'cc','-std=c99','-Wall','-Werror','-fsanitize=address,undefined',str(c),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
