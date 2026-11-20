# Kernel dependency stubs used by the executed C harnesses.
pre = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#undef EOPNOTSUPP
#define EOPNOTSUPP 95
#define CONFIG_CMA 1
#define pr_info(...) ((void)0)
#define pr_err(...) ((void)0)
#define IS_ERR_OR_NULL(p) (!(p))
#define GFP_KERNEL 0
#define IRQF_SHARED 1
#define VDIN_FLAG_ISR_REQ 1
#define VDIN_FLAG_ISR_EN 2
#define VDIN_FLAG_DEC_STARTED 4
#define VDIN_FLAG_DEC_OPENED 8
#define VDIN_FLAG_V4L2_DEBUG 16
#define VDIN_FLAG_FORCE_RECYCLE 32
#define VDIN_FLAG_RDMA_ENABLE 64
#define PARAM_STATE_SCREENCAP 1
#define PARAM_STATE_HISTGRAM 2
#define BT_PATH_GPIO_B 1
#define TVIN_PORT_VIU1 0xa000
#define TVIN_PORT_VIU1_VIDEO 0xa001
#define VPP_POSTBLEND_VD1_V_START_END 0
#define VPP_POSTBLEND_VD1_H_START_END 1
#define rd(a,b) 0
static unsigned int cpu=0x2a;
static int panel_reverse,drop_num,vdin_dbg_en,time_en,viu_hw_irq=1;
static unsigned int jiffies;
static unsigned int jiffies_to_msecs(unsigned int x){return x;}
static int is_meson_gxlx2_cpu(void){return cpu==0x2a;}
static int is_meson_gxbb_cpu(void){return cpu==0x1f;}
enum tvin_sig_fmt_e {TVIN_SIG_FMT_MAX=1000};
struct tvin_format_s {unsigned int hs_bp,vs_bp,hs_pol,vs_pol,h_active,v_active,scan_mode,duration,pixel_clk;};
struct vdin_parm_s {unsigned long reserved;unsigned int dest_hactive,dest_vactive,h_reverse,v_reverse,fmt,hs_bp,vs_bp,hsync_phase,vsync_phase,h_active,v_active,frame_rate,scan_mode,bt_path,port,dest_width,dest_height;struct {unsigned int fmt;} info;};
struct tvin_frontend_s;
struct decops {int (*open)(struct tvin_frontend_s *,unsigned int);void (*close)(struct tvin_frontend_s *);};
struct tvin_frontend_s {void *private_data;unsigned int port;struct decops *dec_ops;};
struct vdin_dev_s {struct vdin_parm_s parm;unsigned int flags,index,hv_reverse_en,frame_cnt,start_time,vdin_max_pixelclk,bt_path,irq,rdma_enable,cma_mem_alloc;char irq_name[16];void *msr_clk;int fe_lock;struct tvin_format_s *fmt_info_p;struct tvin_frontend_s *frontend;struct {int hdcp_sts;} pre_prop,prop;unsigned int matrix_pattern_mode;};
static struct vdin_dev_s *vdin_devp[2],devs[2];static struct tvin_frontend_s fe;
static struct tvin_format_s standard_fmt;
static int clock_error,open_error,irq_error,start_error,missing_frontend;
static unsigned int locks,allocations,freed,clock_refs,opens,closes,irq_registered,irq_frees,starts,hw_disabled,irq_disabled,irq_enabled,cma_frees;
static void mutex_lock(int *p){(void)p;assert(!locks);locks=1;}
static void mutex_unlock(int *p){(void)p;assert(locks);locks=0;}
static void *kmalloc(size_t n,int flags){(void)flags;allocations++;return malloc(n);}
static void kfree(void *p){assert(p);freed++;free(p);}
static struct tvin_format_s *tvin_get_fmt_info(unsigned int fmt){(void)fmt;return &standard_fmt;}
static int fe_open(struct tvin_frontend_s *p,unsigned int port){assert(p==&fe&&port==0xa000);opens++;return open_error;}
static void fe_close(struct tvin_frontend_s *p){assert(p==&fe);closes++;}
static struct tvin_frontend_s *tvin_get_frontend(unsigned int port,int index){(void)port;(void)index;return missing_frontend?NULL:&fe;}
static int clk_prepare_enable(void *p){assert(p);if(!clock_error)clock_refs++;return clock_error;}
static void clk_disable_unprepare(void *p){assert(p&&clock_refs);clock_refs--;}
static int vdin_v4l2_isr(int irq,void *p){(void)irq;(void)p;return 0;}
static int request_irq(unsigned int irq,int (*handler)(int,void *),int flags,const char *name,void *p){(void)irq;(void)handler;(void)flags;(void)name;(void)p;if(!irq_error)irq_registered=1;return irq_error;}
static void disable_irq(unsigned int irq){(void)irq;assert(irq_registered);irq_disabled++;}
static void enable_irq(unsigned int irq){(void)irq;assert(irq_registered);irq_enabled++;}
static void free_irq(unsigned int irq,void *p){(void)irq;(void)p;assert(irq_registered);irq_registered=0;irq_frees++;}
static int vdin_start_dec(struct vdin_dev_s *p){starts++;if(cpu==0x2a)assert(irq_registered&&irq_disabled&&!irq_enabled);if(!start_error)p->cma_mem_alloc=1;return start_error;}
static void vdin_hw_disable(struct vdin_dev_s *p){(void)p;hw_disabled++;}
static void vdin_cma_release(struct vdin_dev_s *p){assert(p->cma_mem_alloc);p->cma_mem_alloc=0;cma_frees++;}
'''
main = r'''
static struct vdin_parm_s param;
static struct decops ops={fe_open,fe_close};
static void init(void){
 memset(devs,0,sizeof(devs));memset(&fe,0,sizeof(fe));memset(&param,0,sizeof(param));
 vdin_devp[0]=&devs[0];vdin_devp[1]=&devs[1];devs[1].index=1;devs[1].msr_clk=&devs[1];devs[1].vdin_max_pixelclk=500000000;devs[1].rdma_enable=1;devs[1].flags=VDIN_FLAG_RDMA_ENABLE;fe.dec_ops=&ops;
 param.port=TVIN_PORT_VIU1;param.fmt=TVIN_SIG_FMT_MAX+1;param.h_active=1280;param.v_active=720;param.frame_rate=60;
 clock_error=open_error=irq_error=start_error=missing_frontend=0;locks=allocations=freed=clock_refs=opens=closes=irq_registered=irq_frees=starts=hw_disabled=irq_disabled=irq_enabled=cma_frees=0;cpu=0x2a;
}
int main(void){
 unsigned int cases=0;
 for(unsigned int failure=0;failure<7;failure++){
  init();switch(failure){case 0:clock_error=-EIO;break;case 1:open_error=-EINVAL;break;case 2:irq_error=-EBUSY;break;case 3:start_error=-ENOMEM;break;case 4:devs[1].msr_clk=NULL;break;case 5:missing_frontend=1;break;case 6:start_error=-EBUSY;break;}
  int ret=start_tvin_service(1,&param);assert(ret<0&&!locks&&allocations==1&&freed==1&&!clock_refs&&!irq_registered&&!devs[1].frontend&&!devs[1].fmt_info_p);
  assert(!(devs[1].flags&(VDIN_FLAG_DEC_STARTED|VDIN_FLAG_DEC_OPENED|VDIN_FLAG_ISR_REQ|VDIN_FLAG_ISR_EN)));
  if(failure==3||failure==6)assert(starts==1&&hw_disabled==1&&irq_frees==1&&closes==1);
  if(failure==2)assert(!starts&&!hw_disabled&&!irq_frees&&closes==1);
  cases++;
 }
 for(unsigned int invalid=0;invalid<5;invalid++){
  init();switch(invalid){case 0:param.frame_rate=0;break;case 1:param.h_active=0;break;case 2:param.v_active=0;break;case 3:param.frame_rate=121;break;case 4:param.h_active=1921;break;}
  assert(start_tvin_service(1,&param)==-EINVAL&&!locks&&!allocations&&!starts);cases++;
 }
 init();assert(start_tvin_service(1,&param)==0&&!locks&&starts==1&&irq_registered&&irq_disabled==1&&irq_enabled==1&&clock_refs==1&&!freed&&!devs[1].rdma_enable);
 assert((devs[1].flags&(VDIN_FLAG_DEC_STARTED|VDIN_FLAG_DEC_OPENED|VDIN_FLAG_ISR_REQ|VDIN_FLAG_ISR_EN))==15);free(devs[1].fmt_info_p);cases++;
 init();cpu=0x21;start_error=-ENOMEM;assert(start_tvin_service(1,&param)==0&&devs[1].rdma_enable==1&&starts==1&&!hw_disabled);free(devs[1].fmt_info_p);cases++;
 printf("PASS: %u actual service-function cases; errors propagate, failed start clears resources/flags, GXLX2 reserves IRQ before start.\n",cases);return 0;
}
'''
