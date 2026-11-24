from pathlib import Path
import os
import subprocess,tempfile,shutil,json
H=Path(os.environ["E900_CAPTURE_TEST_ROOT"])
pre=r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/types.h>
#ifdef __APPLE__
typedef off_t loff_t;
#endif
#undef EOPNOTSUPP
#define EOPNOTSUPP 95
#define ERESTARTSYS 512
#define CONFIG_CMA 1
#define BUILD_BUG_ON(x) _Static_assert(!(x),"layout")
typedef uint64_t u64;typedef uint32_t __le32;typedef uint64_t __le64;typedef int mm_segment_t;
#define cpu_to_le32(x) ((uint32_t)(x))
#define cpu_to_le64(x) ((uint64_t)(x))
#define VDIN_FLAG_DEC_STARTED 1
#define VDIN_FLAG_V4L2_DEBUG 2
#define VDIN_FLAG_SUSPEND 4
#define VDIN_FLAG_RDMA_ENABLE 8
#define VF_FLAG_NORMAL_FRAME 1
#define VF_FLAG_FREEZED_FRAME 2
#define VDIN_VF_POOL_FREEZE 1
#define VDIN_CANVAS_MAX_CNT 10
#define VDIN_WORK_MD_E900_CAPTURE 2
#define TVIN_SCAN_MODE_PROGRESSIVE 0
#define VDIN_FORMAT_CONVERT_YUV_YUV444 1
#define VDIN_FORMAT_CONVERT_YUV_RGB 2
#define VDIN_FORMAT_CONVERT_RGB_YUV444 3
#define VDIN_FORMAT_CONVERT_RGB_RGB 4
#define KERNEL_DS 1
#define pr_err(...) ((void)0)
static void snapshot_log(const char *format,...){(void)format;}
#define pr_info snapshot_log
struct vf_entry {struct {unsigned int index;uint64_t timestamp;} vf;unsigned int flag;};
struct vf_pool {unsigned int pool_flag;struct vf_entry *ready;};
struct device {int unused;};struct platform_device {struct device dev;};struct page {int unused;};struct fmt {int scan_mode;};
struct vdin_dev_s {unsigned int index,flags,rdma_enable,afbce_mode,source_bitdepth,cma_mem_alloc,matrix_pattern_mode,secure_en,mem_protected,canvas_h,canvas_w,canvas_active_w,frame_size,vfmem_max_cnt,format_convert,frame_cnt,pause_dec,work_mode;bool e900_dma_mapped;struct platform_device *this_pdev;struct page *venc_pages;struct fmt *fmt_info_p;int fe_lock,isr_lock;struct vf_pool *vfp;struct vf_entry *curr_wr_vfe,*last_wr_vfe;};
static unsigned int cpu=0x2a,device_locked,fe_locked,spin_locked,held,cpu_owned,recycled,restored,allocs,frees,sleeps,copy_rows;
static int device_busy,lock_error,alloc_error,sync_cpu_error,sync_device_error,page_error,interrupt_sleep,ready_after;
static unsigned long jiffies;static uint64_t jiffies_64;
static unsigned char memory[64];static struct vf_entry frame;
static int is_meson_gxlx2_cpu(void){return cpu==0x2a;}
static int device_trylock(struct device *d){assert(d&&!device_locked);if(device_busy)return 0;device_locked=1;return 1;}
static void device_unlock(struct device *d){assert(d&&device_locked);device_locked=0;}
static int mutex_lock_interruptible(int *p){(void)p;assert(device_locked&&!fe_locked);if(lock_error)return lock_error;fe_locked=1;return 0;}
static void mutex_unlock(int *p){(void)p;assert(fe_locked);fe_locked=0;}
#define spin_lock_irqsave(l,f) do {(void)(l);assert(fe_locked&&!spin_locked);spin_locked=1;(f)=0;} while(0)
#define spin_unlock_irqrestore(l,f) do {(void)(l);(void)(f);assert(spin_locked);spin_locked=0;} while(0)
static void *vmalloc(size_t n){assert(fe_locked&&!spin_locked);if(alloc_error)return NULL;void *p=malloc(n);assert(p);allocs++;return p;}
static void vfree(void *p){assert(!spin_locked);if(p){frees++;free(p);}}
static struct vf_entry *receiver_vf_get(struct vf_pool *p){assert(spin_locked);if(!p->ready)return NULL;assert(!held);struct vf_entry *f=p->ready;p->ready=NULL;held=1;return f;}
static void provider_vf_put(struct vf_entry *f,struct vf_pool *p){assert(spin_locked&&held&&!cpu_owned);p->ready=f;held=0;restored++;}
static void receiver_vf_put(void *vf,struct vf_pool *p){(void)vf;(void)p;assert(held&&!cpu_owned);held=0;recycled++;}
static unsigned long msecs_to_jiffies(unsigned long x){return x;}
#define time_after_eq(a,b) ((long)((a)-(b))>=0)
static struct vf_pool pool;
static int msleep_interruptible(unsigned int ms){assert(fe_locked&&device_locked&&!spin_locked&&!held);jiffies+=ms;jiffies_64+=ms;sleeps++;if(ready_after>0&&sleeps==(unsigned int)ready_after){frame.vf.timestamp=jiffies_64;pool.ready=&frame;}return interrupt_sleep;}
static int e900_vdin_dma_sync_frame(struct vdin_dev_s *d,unsigned int idx,bool for_cpu){assert(d&&fe_locked&&held&&!spin_locked&&idx==frame.vf.index);if(for_cpu){assert(!cpu_owned);if(sync_cpu_error)return sync_cpu_error;cpu_owned=1;}else{assert(cpu_owned);if(sync_device_error)return sync_device_error;cpu_owned=0;}return 0;}
static void *page_address(struct page *p){assert(p&&held&&cpu_owned&&!spin_locked);return page_error?NULL:memory;}
static void *checked_copy(void *dest,const void *src,size_t n){uintptr_t a=(uintptr_t)src,lo=(uintptr_t)memory;if(a>=lo&&a<lo+sizeof(memory)){assert(held&&cpu_owned&&!spin_locked&&a+n<=lo+sizeof(memory));copy_rows++;}return memcpy(dest,src,n);}
#define memcpy checked_copy
struct file {int unused;};static struct file output_file;
static int open_error,write_error_at,write_zero_at,fsync_error,close_error,fs_state;
static unsigned int opened,closed,writes,fsyncs;static size_t file_size,write_chunk;static unsigned char file_data[1024];
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
#define PTR_ERR(p) ((long)(intptr_t)(p))
static struct file *filp_open(const char *p,int flags,int mode){assert(p&&mode==0600&&(flags&O_NOFOLLOW)&&!device_locked&&!fe_locked&&!held&&!cpu_owned);opened++;return open_error?(struct file *)(intptr_t)open_error:&output_file;}
static mm_segment_t get_fs(void){return fs_state;}
static void set_fs(mm_segment_t n){fs_state=n;}
static ssize_t vfs_write(struct file *f,const void *data,size_t n,off_t *pos){assert(f&&fs_state==1&&!held&&!cpu_owned&&!fe_locked);writes++;if(write_error_at==(int)writes)return -EIO;if(write_zero_at==(int)writes)return 0;if(write_chunk&&n>write_chunk)n=write_chunk;assert(file_size+n<=sizeof(file_data));memcpy(file_data+file_size,data,n);file_size+=n;*pos+=n;return n;}
static int vfs_fsync(struct file *f,int data){(void)data;assert(f&&fs_state==0);fsyncs++;return fsync_error;}
static int filp_close(struct file *f,void *p){(void)p;assert(f&&fs_state==0);closed++;return close_error;}
'''
main=r'''
static struct vdin_dev_s dev;static struct platform_device platform;static struct page pages;static struct fmt format;
static void init(void){
 memset(&dev,0,sizeof(dev));memset(&pool,0,sizeof(pool));memset(&frame,0,sizeof(frame));
 cpu=0x2a;device_locked=fe_locked=spin_locked=held=cpu_owned=recycled=restored=allocs=frees=sleeps=copy_rows=0;
 device_busy=lock_error=alloc_error=sync_cpu_error=sync_device_error=page_error=interrupt_sleep=ready_after=0;
 opened=closed=writes=fsyncs=0;file_size=write_chunk=0;open_error=write_error_at=write_zero_at=fsync_error=close_error=fs_state=0;
 jiffies=100;jiffies_64=100;frame.vf.index=2;frame.vf.timestamp=100;frame.flag=VF_FLAG_NORMAL_FRAME;pool.ready=&frame;
 dev.index=1;dev.flags=VDIN_FLAG_DEC_STARTED|VDIN_FLAG_V4L2_DEBUG;dev.source_bitdepth=8;dev.e900_dma_mapped=true;dev.cma_mem_alloc=1;dev.this_pdev=&platform;dev.venc_pages=&pages;format.scan_mode=0;dev.fmt_info_p=&format;dev.vfp=&pool;dev.canvas_h=2;dev.canvas_w=8;dev.canvas_active_w=6;dev.frame_size=16;dev.vfmem_max_cnt=4;dev.format_convert=VDIN_FORMAT_CONVERT_YUV_RGB;dev.frame_cnt=99;dev.work_mode=VDIN_WORK_MD_E900_CAPTURE;
 for(size_t i=0;i<sizeof(memory);i++)memory[i]=(unsigned char)i;
}
static void clean(void){assert(!device_locked&&!fe_locked&&!spin_locked&&!held&&!cpu_owned&&allocs==frees&&fs_state==0);}
int main(int argc,char **argv){
 unsigned int cases=0;void *packet=(void *)1;size_t size=1;
 init();assert(!e900_vdin_snapshot_copy(&dev,&packet,&size)&&size==92);struct e900_vdin_snapshot_header *h=packet;assert(!memcmp(h->magic,"E9VDIN1",8)&&h->version==1&&h->header_bytes==80&&h->width==2&&h->height==2&&h->source_stride==8&&h->frame_index==2&&h->payload_bytes==12&&h->frame_timestamp==100&&h->completion_count==99&&h->flags==3);assert(!memcmp((char *)packet+80,memory+32,6)&&!memcmp((char *)packet+86,memory+40,6)&&copy_rows==2&&recycled==1);if(argc==2){FILE *f=fopen(argv[1],"wb");assert(f&&fwrite(packet,1,size,f)==size);fclose(f);}vfree(packet);clean();cases++;
 for(unsigned int bad=0;bad<23;bad++){
  init();switch(bad){case 0:cpu=0x21;break;case 1:dev.index=0;break;case 2:device_busy=1;break;case 3:lock_error=-EINTR;break;case 4:dev.flags=0;break;case 5:dev.source_bitdepth=10;break;case 6:dev.flags|=VDIN_FLAG_RDMA_ENABLE;break;case 7:dev.rdma_enable=1;break;case 8:dev.afbce_mode=1;break;case 9:dev.secure_en=1;break;case 10:dev.mem_protected=1;break;case 11:dev.matrix_pattern_mode=4;break;case 12:format.scan_mode=1;break;case 13:dev.canvas_active_w=9;break;case 14:dev.canvas_active_w=5;break;case 15:dev.canvas_h=0;break;case 16:dev.frame_size=15;break;case 17:dev.canvas_h=1081;break;case 18:dev.e900_dma_mapped=0;break;case 19:dev.format_convert=99;break;case 20:alloc_error=1;break;case 21:dev.pause_dec=1;break;case 22:dev.work_mode=0;break;}
  packet=(void *)1;size=1;assert(e900_vdin_snapshot_copy(&dev,&packet,&size)<0&&!packet&&!size&&!copy_rows&&!recycled);clean();cases++;
 }
 for(unsigned int bad=0;bad<6;bad++){
  init();struct vf_entry active={0};active.vf.index=2;switch(bad){case 0:pool.pool_flag=VDIN_VF_POOL_FREEZE;break;case 1:dev.curr_wr_vfe=&active;break;case 2:dev.last_wr_vfe=&active;break;case 3:frame.flag=0;break;case 4:frame.flag|=VF_FLAG_FREEZED_FRAME;break;case 5:frame.vf.index=10;break;}
  assert(e900_vdin_snapshot_copy(&dev,&packet,&size)<0&&!copy_rows&&!packet);assert(!recycled||bad==4);clean();cases++;
 }
 init();frame.vf.timestamp=99;assert(e900_vdin_snapshot_copy(&dev,&packet,&size)==-ETIMEDOUT&&recycled==1&&!copy_rows);clean();cases++;
 init();frame.vf.timestamp=99;ready_after=3;assert(!e900_vdin_snapshot_copy(&dev,&packet,&size)&&recycled==2&&sleeps==3);assert(((struct e900_vdin_snapshot_header*)packet)->frame_timestamp==160);vfree(packet);clean();cases++;
 init();pool.ready=NULL;assert(e900_vdin_snapshot_copy(&dev,&packet,&size)==-ETIMEDOUT&&sleeps==100&&!copy_rows);clean();cases++;
 init();pool.ready=NULL;interrupt_sleep=1;assert(e900_vdin_snapshot_copy(&dev,&packet,&size)==-ERESTARTSYS&&sleeps==1&&!copy_rows);clean();cases++;
 init();pool.ready=NULL;ready_after=3;assert(!e900_vdin_snapshot_copy(&dev,&packet,&size)&&sleeps==3);vfree(packet);clean();cases++;
 init();pool.ready=NULL;jiffies=(unsigned long)-1000;assert(e900_vdin_snapshot_copy(&dev,&packet,&size)==-ETIMEDOUT&&sleeps==100);clean();cases++;
 init();sync_cpu_error=-EIO;assert(e900_vdin_snapshot_copy(&dev,&packet,&size)==-EIO&&recycled==1&&!copy_rows);clean();cases++;
 init();page_error=1;assert(e900_vdin_snapshot_copy(&dev,&packet,&size)==-EFAULT&&recycled==1&&!copy_rows);clean();cases++;
 for(unsigned int fail=0;fail<6;fail++){
  init();switch(fail){case 0:open_error=-EACCES;break;case 1:write_error_at=1;break;case 2:write_chunk=3;write_zero_at=2;break;case 3:fsync_error=-EIO;break;case 4:close_error=-EIO;break;case 5:write_chunk=3;break;}
  int ret=e900_vdin_snapshot_save(&dev,"snapshot.partial");assert((fail==5)?ret==0:ret<0);assert(recycled==1&&opened==1&&closed==(fail?1U:0U));clean();cases++;
 }
 init();sync_device_error=-EIO;assert(e900_vdin_snapshot_copy(&dev,&packet,&size)==-EIO&&!packet&&held&&cpu_owned&&dev.pause_dec&&!recycled&&allocs==frees&&!fe_locked&&!device_locked);cases++;
 printf("PASS: %u actual snapshot/save cases; owned copy, geometry/target rejection, timeout/signal and I/O cleanup. DMA handback failure quarantines the frame.\n",cases);return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='e900-snapshot-') as t:
 f=Path(t)/'test.c';f.write_text(pre+(H/'snapshot.c').read_text()+main);exe=f.with_suffix('')
 subprocess.run([shutil.which('clang') or 'cc','-std=gnu11','-Wall','-Werror','-fsanitize=address,undefined',str(f),'-o',str(exe)],check=True)
 out=subprocess.check_output([str(exe),str(H/'synthetic.e9cap')],text=True);print(out,end='')
(H/'host-checks.json').write_text(json.dumps({'result':out.strip(),'scope':'Complete new snapshot copy/save C functions with mocked device/mutex/spin locks, ready queue, DMA APIs, allocator, clock/sleep and filesystem, under ASan/UBSan. Does not validate actual DMA completion/coherency, concurrent kernel races or full ARM compilation. synthetic.e9cap is synthetic, not device evidence.'},indent=2)+'\n')
