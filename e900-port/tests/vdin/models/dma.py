# Kernel dependency stubs used by the executed C harnesses.
pre = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#undef EOPNOTSUPP
#define EOPNOTSUPP 95
#define VDIN_CANVAS_MAX_CNT 10
#define DMA_FROM_DEVICE 2
#define CONFIG_AMLOGIC_TEE 1
struct device {int unused;};struct platform_device {struct device dev;};struct page {bool high;};
typedef uint64_t dma_addr_t;
struct vdin_dev_s {struct platform_device *this_pdev;unsigned int index,cma_config_flag,mem_size,cma_mem_alloc,frame_size,vfmem_max_cnt,afbce_mode;struct page *venc_pages;uint64_t mem_start,vfmem_start[VDIN_CANVAS_MAX_CNT];dma_addr_t e900_dma_address;size_t e900_dma_size;bool e900_dma_mapped,secure_en,mem_protected,cma_config_en;unsigned int secure_handle;struct page *vfvenc_pages[VDIN_CANVAS_MAX_CNT];};
static unsigned int cpu=0x2a,events;static dma_addr_t mapped_address;static bool fail_map,map_live;static size_t last_offset,last_size;
static int is_meson_gxlx2_cpu(void) {return cpu==0x2a;}
#define PageHighMem(p) ((p)->high)
static dma_addr_t dma_map_page(struct device *d,struct page *p,size_t offset,size_t size,int dir) {assert(d&&p&&offset==0&&size&&dir==2);events++;last_size=size;map_live=!fail_map;return mapped_address;}
static bool dma_mapping_error(struct device *d,dma_addr_t a) {(void)d;assert(a==mapped_address);return fail_map;}
static void dma_unmap_page(struct device *d,dma_addr_t a,size_t size,int dir) {assert(d&&a==mapped_address&&size==last_size&&dir==2&&map_live);map_live=false;events++;}
static void dma_sync_single_range_for_cpu(struct device *d,dma_addr_t a,size_t off,size_t size,int dir) {assert(d&&a==mapped_address&&dir==2);events++;last_offset=off;assert(size==0x1000);}
static void dma_sync_single_range_for_device(struct device *d,dma_addr_t a,size_t off,size_t size,int dir) {assert(d&&a==mapped_address&&dir==2);events++;last_offset=off;assert(size==0x1000);}
'''
extra = r'''
#define MEM_ALLOC_DISCRETE 0x100
#define MEM_ALLOC_FROM_CODEC 1
#define PAGE_SHIFT 12
#define pr_info(...) ((void)0)
#define pr_err(...) ((void)0)
static unsigned int frees;
static void codec_mm_free_for_dma(const char *name,unsigned long addr) {(void)name;(void)addr;frees++;}
static void tee_unprotect_mem(unsigned int h) {(void)h;}
static bool dma_release_from_contiguous(struct device *d,struct page *p,size_t count) {assert(d&&p&&count&&!map_live);frees++;return true;}
'''
main = r'''
static struct platform_device platform;static struct page page;
static struct vdin_dev_s dev;
static unsigned int cases;
static void init(void) {
 memset(&dev,0,sizeof(dev));page.high=false;dev.this_pdev=&platform;dev.index=1;dev.venc_pages=&page;dev.mem_size=0x4000;dev.mem_start=0x35400000;dev.frame_size=0x1000;dev.vfmem_max_cnt=4;dev.cma_mem_alloc=1;dev.cma_config_en=1;frees=0;
 for(unsigned int i=0;i<4;i++)dev.vfmem_start[i]=dev.mem_start+0x1000*i;
 cpu=0x2a;events=0;fail_map=false;map_live=false;mapped_address=dev.mem_start;last_size=0;
}
int main(void) {
 for(unsigned int other=0;other<0x40;other++) {
  if(other==0x2a)continue;init();cpu=other;assert(e900_vdin_dma_map(&dev)==0&&!events&&!dev.e900_dma_mapped);cases++;
 }
 init();dev.index=0;assert(!e900_vdin_dma_map(&dev)&&!events);cases++;
 for(unsigned int bad=0;bad<9;bad++) {
  init();switch(bad) {
   case 0:dev.e900_dma_mapped=true;break;case 1:dev.cma_config_flag=1;break;case 2:dev.venc_pages=NULL;break;case 3:dev.mem_size=0;break;case 4:page.high=true;break;case 5:dev.cma_config_flag=0x100;break;case 6:dev.afbce_mode=1;break;case 7:dev.secure_en=true;break;case 8:dev.mem_protected=true;break;
  }
  assert(e900_vdin_dma_map(&dev)==-EOPNOTSUPP&&!events);cases++;
 }
 init();fail_map=true;assert(e900_vdin_dma_map(&dev)==-EIO&&events==1&&!dev.e900_dma_mapped);e900_vdin_dma_unmap(&dev);assert(events==1);cases++;
 init();mapped_address+=0x1000;assert(e900_vdin_dma_map(&dev)==-EOPNOTSUPP&&events==2&&!dev.e900_dma_mapped);e900_vdin_dma_unmap(&dev);assert(events==2);cases++;
 for(unsigned int index=0;index<4;index++) {
  init();assert(!e900_vdin_dma_map(&dev)&&dev.e900_dma_mapped&&events==1);
  assert(!e900_vdin_dma_sync_frame(&dev,index,true)&&events==2&&last_offset==index*0x1000);
  assert(!e900_vdin_dma_sync_frame(&dev,index,false)&&events==3);
  e900_vdin_dma_unmap(&dev);assert(events==4&&!dev.e900_dma_mapped&&!dev.e900_dma_size&&!dev.e900_dma_address);
  e900_vdin_dma_unmap(&dev);assert(events==4);assert(e900_vdin_dma_sync_frame(&dev,index,true)==-EINVAL&&events==4);cases++;
 }
 for(unsigned int bad=0;bad<9;bad++) {
  init();assert(!e900_vdin_dma_map(&dev));unsigned int index=0;
  switch(bad) {
   case 0:dev.cma_mem_alloc=0;break;case 1:dev.frame_size=0;break;case 2:index=4;break;case 3:index=UINT32_MAX;break;case 4:dev.e900_dma_size=0xfff;break;case 5:dev.vfmem_start[0]--;break;case 6:dev.vfmem_start[0]++;break;case 7:dev.frame_size=UINT32_MAX;index=3;break;case 8:dev.vfmem_max_cnt=UINT32_MAX;index=VDIN_CANVAS_MAX_CNT;break;
  }
  assert(e900_vdin_dma_sync_frame(&dev,index,true)<0&&events==1);cases++;
 }
 init();dev.mem_start=0;mapped_address=0;assert(!e900_vdin_dma_map(&dev)&&dev.e900_dma_mapped);e900_vdin_dma_unmap(&dev);assert(events==2);cases++;
 init();assert(!e900_vdin_dma_map(&dev));vdin_cma_release(&dev);assert(events==2&&frees==1&&!dev.e900_dma_mapped&&!dev.cma_mem_alloc&&!dev.mem_size);vdin_cma_release(&dev);assert(events==2&&frees==1);cases++;
 init();mapped_address+=0x1000;assert(e900_vdin_dma_map(&dev)<0&&events==2);vdin_cma_release(&dev);assert(events==2&&frees==1&&!dev.cma_mem_alloc);cases++;
 init();fail_map=true;assert(e900_vdin_dma_map(&dev)<0&&events==1);vdin_cma_release(&dev);assert(events==1&&frees==1&&!dev.cma_mem_alloc);cases++;
 printf("PASS: %u DMA helper cases; bounded sync, failure cleanup, translation rejection and non-GXLX2 behavior.\n",cases);
 return 0;
}
'''
