#!/usr/bin/env python3
"""Exercise the patched dispatch, notifier and fixed video register completion.

MMIO, mutexes and the kernel notifier implementation are host models; ARM linking,
real IRQ ordering and hardware register support still require a native build/test.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

PORT = Path(__file__).resolve().parents[1]
AUDIT = Path(os.environ.get('E900_AUDIT_ROOT', PORT.parent / 'coreelec-audit'))
OPS = 'drivers/amlogic/media/common/arch/registers/register_ops.c'
HEADER = 'include/linux/amlogic/media/registers/register_ops.h'
HW = 'drivers/amlogic/media/video_sink/video_hw.c'
VIDEO = 'drivers/amlogic/media/video_sink/video.c'


def function(source, name):
    m = re.search(r'^(?:static )?(?:unsigned int|bool|int|void)(?: __(?:init|exit))? '
                  + name + r'\([^;]*?\)\s*\{', source, re.M)
    assert m, name
    start = source.index('{', m.start())
    depth, end = 1, start + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[m.start():end] + '\n'


with tempfile.TemporaryDirectory(prefix='e900-video-init-') as directory:
    root = Path(directory)
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    for row in json.loads((PORT / 'tests/source-fixtures.json').read_text()):
        if row['repo'] != 'CoreELEC/linux-amlogic':
            continue
        data = (AUDIT / 'sources' / row['path'].replace('/', '__')).read_bytes()
        assert hashlib.sha256(data).hexdigest() == row['sha256'], row['path']
        dest = root / row['path']
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    for patch in sorted((PORT / 'patches/linux').glob('*.patch')):
        if patch.name.startswith('0019-'):
            before = (root / HW).read_text()
        subprocess.run(['git', 'apply', str(patch)], cwd=root, check=True)
    hw, ops, header, video = [(root / path).read_text() for path in (HW, OPS, HEADER, VIDEO)]
    branch = ('\tif (is_meson_gxlx2_cpu() && gxlx2_hw_init)\n'
              '\t\treturn gxlx2_video_hw_prepare();\n\n')
    baseline = function(before, 'video_hw_init')
    baseline = baseline.replace('else if (cpu_after_eq(MESON_CPU_MAJOR_ID_G12B)) {',
        'else if (cpu_after_eq(MESON_CPU_MAJOR_ID_G12B) &&\n'
        '\t\t   (!is_meson_gxlx2_cpu() ||\n'
        '\t\t    (sr_info.sr_support & SUPER_CORE0_SUPPORT))) {')
    assert function(hw, 'video_hw_init').replace(branch, '') == baseline
    assert 'sr_info.sr_support & SUPER_CORE0_SUPPORT' in function(hw, 'gxlx2_video_hw_apply')
    assert 'module_init(video_init);' in video and 'e900_video_init_late' not in video
    assert video.index('video_debugfs_init();') < video.index('gxlx2_video_hw_complete();')
    assert function(video, 'amvideom_probe').count('gxlx2_video_hw_probe_done();') == 1
    assert function(video, 'amvideom_remove').count('gxlx2_video_hw_cancel();') == 1
    assert function(video, 'video_exit').count('gxlx2_video_hw_cancel();') == 1
    helper = hw[hw.index('/* Keep probe/software/security setup early;'):hw.index('int video_hw_init(void)')]
    # Compare the deferred write order/values against the real upstream CPU=0x2a branch.
    apply = function(hw, 'gxlx2_video_hw_apply')
    assert apply.count('gxlx2_hw_write(') == 5
    assert apply.count('gxlx2_hw_update_bits(') == 4
    assert apply.count('gxlx2_hw_read(') == 4
    assert 'video_hw_init();' not in helper and 'video_init();' not in helper
    assert 'WRITE_VCBUS_REG(VPP_HOLD_LINES' not in helper
    buses = header[header.index('enum\n'):header.index('};') + 2]
    start = header.index('struct chip_register_ops {')
    struct = header[start:header.index('};', start) + 2]
    c = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <stdarg.h>
typedef uint32_t u32;
#define GFP_KERNEL 0
#define MESON_CPU_MAJOR_ID_G12A 0x28
#define AIU_AIFIFO_CTRL 0
#define AIU_MEM_AIFIFO_MEM_CTL 255
#define CODEC_OPS_START(...) ((void)0)
#define CODEC_OPS_ERROR(...) ((void)0)
#define pr_debug(...) ((void)0)
static unsigned trace_reads_begin[14],trace_reads_end[14],trace_writes_begin[14],trace_writes_end[14];
static unsigned active_step,active_op;
static void trace_log(const char *fmt,...) {
    if (!strstr(fmt,"step=%u")) return;
    va_list args; va_start(args,fmt); unsigned step=va_arg(args,unsigned); va_end(args);
    assert(step>0 && step<14); active_step=step;
    if(strstr(fmt,"read.begin")) {trace_reads_begin[step]++;active_op=1;}
    if(strstr(fmt,"read.end")) {trace_reads_end[step]++;active_op=0;}
    if(strstr(fmt,"write.begin")) {trace_writes_begin[step]++;active_op=2;}
    if(strstr(fmt,"write.end")) {trace_writes_end[step]++;active_op=0;}
}
#define pr_info(...) trace_log(__VA_ARGS__)
#define pr_err(...) ((void)0)
#define EXPORT_SYMBOL(...)
#define module_param_named(...)
#define module_param_cb(name,ops,arg,mode) static const void *use_##name __attribute__((unused)) = ops
#define MODULE_PARM_DESC(...)
#define DEFINE_MUTEX(name) int name
#define mutex_lock(p) do { assert(!*(p)); *(p)=1; } while (0)
#define mutex_unlock(p) do { assert(*(p)); *(p)=0; } while (0)
#define min_t(type,a,b) ((type)(a)<(type)(b)?(type)(a):(type)(b))
#define NOTIFY_OK 1
#define NOTIFY_BAD 0x8002
#define CONFIG_AMLOGIC_MEDIA_SECURITY 1
struct notifier_block {int (*notifier_call)(struct notifier_block *,unsigned long,void *);};
struct fake_chain {struct notifier_block *nb;};
#define BLOCKING_NOTIFIER_HEAD(name) struct fake_chain name
static int subscribe_error;
static int blocking_notifier_chain_register(struct fake_chain *c,struct notifier_block *nb) {
    if (subscribe_error) return -ENOMEM;
    assert(!c->nb); c->nb=nb; return 0;
}
static int blocking_notifier_chain_unregister(struct fake_chain *c,struct notifier_block *nb) {
    assert(c->nb==nb); c->nb=NULL; return 0;
}
static int blocking_notifier_call_chain(struct fake_chain *c,unsigned long event,void *data) {
    return c->nb ? c->nb->notifier_call(c->nb,event,data) : 0;
}
''' + buses + '\n' + struct + r'''
static void e900_debug_event(const char*s,unsigned a,unsigned b,unsigned c,unsigned d){(void)s;(void)a;(void)b;(void)c;(void)d;}
/* Executed independently by check-gen3-rmw-osd.py. */
static void e900_gen3_rmw(unsigned reg,int handle,int mode,unsigned start,unsigned len,unsigned hardware,unsigned base,unsigned result,int source,void*caller){(void)reg;(void)handle;(void)mode;(void)start;(void)len;(void)hardware;(void)base;(void)result;(void)source;(void)caller;}
/* Timeline behavior is exercised separately by check-playback-timeline.py. */
#define E900_PB_DIRECT 4
#define E900_PB_WORD 4
#define E900_PB_CANCEL 6
static bool e900_playback_direct_selected(unsigned r) {return (r>=0x1a00&&r<=0x1aff)||(r>=0x1d00&&r<=0x1dff)||(r>=0x3800&&r<=0x38ff)||(r>=0x3d60&&r<=0x3d6f);}
static void e900_playback_note(unsigned s,unsigned k,unsigned se,unsigned b,unsigned h,unsigned r,unsigned v,unsigned a){(void)s;(void)k;(void)se;(void)b;(void)h;(void)r;(void)v;(void)a;}
static struct chip_register_ops *amports_ops[BUS_MAX];
static unsigned e900_bus_write_drops[BUS_MAX];
#define atomic_inc(p) (++*(p))
static int cpu=0x2a, allocation_error, writes, reads;
static u32 regs[32];
static bool corrupt_readback;
static int get_cpu_type(void) {return cpu;}
static bool is_meson_gxlx2_cpu(void) {return cpu==0x2a;}
static void *allocations[64];
static unsigned allocation_count;
static void *kmalloc_array(size_t count,size_t size,int flags) {
    (void)flags;
    if (allocation_error) return NULL;
    assert(allocation_count<64);
    return allocations[allocation_count++]=calloc(count,size);
}
static int fake_read(unsigned reg) {
    assert(amports_ops[IO_VC_BUS] && reg<32); reads++;
    assert(active_op==1 && trace_reads_begin[active_step]==trace_reads_end[active_step]+1);
    if (corrupt_readback && reg==1) return 0;
    return regs[reg];
}
static void fake_write(unsigned reg,unsigned value) {
    assert(amports_ops[IO_VC_BUS] && reg<32); writes++; regs[reg]=value;
    assert(active_op==2 && trace_writes_begin[active_step]==trace_writes_end[active_step]+1);
}
'''
    for name in ['codec_reg_bus_ready', 'codec_reg_read', 'codec_reg_write', 'codec_reg_write_bits']:
        c += function(ops, name)
    notifier_start = ops.index('static BLOCKING_NOTIFIER_HEAD(codec_reg_ready_chain);')
    c += ops[notifier_start:ops.index('\nint codec_reg_read(', notifier_start)]
    c += '#pragma GCC diagnostic push\n#pragma GCC diagnostic ignored "-Wempty-body"\n'
    c += function(ops, 'register_reg_onebus_ops')
    c += '#pragma GCC diagnostic pop\n' + function(ops, 'register_reg_ops_per_cpu')
    c += r'''
#define VPP_OFIFO_SIZE 0
#define VPP_PREBLEND_VD1_H_START_END 1
#define VPP_BLEND_VD2_H_START_END 2
#define VPP_DUMMY_DATA 3
#define VPP_SRSHARP0_CTRL 4
#define VPP_SRSHARP1_CTRL 5
#define DOLBY_PATH_CTRL 7
#define VPP_HOLD_LINES 8
#define VPP_OFIFO_SIZE_BIT 0
#define VPP_OFIFO_SIZE_WID 12
#define WRITE_VCBUS_REG(r,v) codec_reg_write(IO_VC_BUS,r,v)
#define READ_VCBUS_REG(r) codec_reg_read(IO_VC_BUS,r)
#define WRITE_VCBUS_REG_BITS(r,v,s,n) codec_reg_write_bits(IO_VC_BUS,r,v,s,n)
#define VPU_VPU_ARB 0
#define VPU_MEM_POWER_ON 0
#define VIDEO_MODULE 0
#define VSYNC_WR_MPEG_REG 0
#define vpp_secure_cb 0
struct kernel_param {void *arg;};
struct kernel_param_ops {int (*set)(const char *,const struct kernel_param *);int (*get)(char *,const struct kernel_param *);};
static int kstrtobool(const char *s,bool *v) {
    if(!strcmp(s,"1") || !strcmp(s,"true")) {*v=true;return 0;}
    if(!strcmp(s,"0") || !strcmp(s,"false")) {*v=false;return 0;}
    return -EINVAL;
}
static int param_get_bool(char *p,const struct kernel_param *kp) {(void)p;return *(bool *)kp->arg;}
static bool legacy_vpp=true,vd1_vd2_mux;
static struct {bool vd1_vd2_mux;void *dispbuf;} vd_layer[2];
static struct {bool dv_support,fgrain_support;} glayer_info[2];
#define SUPER_CORE0_SUPPORT 1U
#define SUPER_CORE1_SUPPORT 2U
static struct {unsigned sr0_sharp_sync_ctrl,sr_support;} sr_info={6,SUPER_CORE0_SUPPORT};
static struct {unsigned vpp_off;} video_dev,*cur_dev=&video_dev;
static u32 vpp_hold_line=8;
static int power_calls,di_calls,security_calls;
static void di_used_vd1_afbc(bool b) {(void)b; di_calls++;}
static void switch_vpu_mem_pd_vmod(int a,int b) {(void)a;(void)b;power_calls++;}
static void secure_register(int a,int b,int c,int d) {(void)a;(void)b;(void)c;(void)d;security_calls++;}
''' + helper + r'''
static void reset(void) {
    gxlx2_video_hw_cancel();
    for (unsigned i=0;i<allocation_count;i++) free(allocations[i]);
    allocation_count=0; memset(amports_ops,0,sizeof(amports_ops)); memset(regs,0,sizeof(regs));
    cpu=0x2a; allocation_error=subscribe_error=writes=reads=0;
    memset(trace_reads_begin,0,sizeof(trace_reads_begin));memset(trace_reads_end,0,sizeof(trace_reads_end));
    memset(trace_writes_begin,0,sizeof(trace_writes_begin));memset(trace_writes_end,0,sizeof(trace_writes_end));
    active_step=active_op=0;
    power_calls=di_calls=security_calls=0;
    corrupt_readback=false; legacy_vpp=true; gxlx2_hw_init=true; vpp_hold_line=8;
    gxlx2_hw_init_wait=false;vd_layer[0].dispbuf=vd_layer[1].dispbuf=NULL;
    sr_info.sr_support=SUPER_CORE0_SUPPORT;
    glayer_info[0].dv_support=false;
    glayer_info[0].fgrain_support=glayer_info[1].fgrain_support=false;
}
static int publish(int n) {
    struct chip_register_ops table[]={
        {IO_VC_BUS,0,fake_read,fake_write,0,0},
        {IO_HHI_BUS,0,fake_read,fake_write,0,0},
        {IO_DMC_BUS,0,fake_read,fake_write,0,0}
    };
    return register_reg_ops_per_cpu(cpu,table,n);
}
static void probe(void) {
    assert(gxlx2_video_hw_prepare()==0);
    gxlx2_video_hw_probe_done();
    gxlx2_video_hw_complete();
}
int main(void) {
    assert(gxlx2_hw_init);
    /* Early software setup runs once, with no dropped or fake register access. */
    for (unsigned hold=0;hold<=255;hold+=17) {
        reset(); regs[VPP_HOLD_LINES]=hold;
        probe();
        assert(!writes && !reads && !e900_bus_write_drops[IO_VC_BUS] && vpp_hold_line==8 && gxlx2_hw_init_status==1);
        assert(power_calls==1 && di_calls==1 && security_calls==1);
        allocation_error=1; assert(publish(3)==-ENOMEM && !writes && !reads);
        allocation_error=0; assert(publish(3)==0);
        assert(writes==9 && gxlx2_hw_done && gxlx2_hw_init_status==2);
        assert(gxlx2_hw_init_step==13);
        for(unsigned step=1;step<=13;step++) {
            unsigned expected_read=(step==1 || step==7 || step==8 || step==9 || step>=10);
            unsigned expected_write=step<=9;
            assert(trace_reads_begin[step]==expected_read && trace_reads_end[step]==expected_read);
            assert(trace_writes_begin[step]==expected_write && trace_writes_end[step]==expected_write);
        }
        assert(vpp_hold_line==(hold>31?31:hold));
        assert((regs[0]&0xfff)==0xfff && regs[1]==4096 && regs[2]==4096);
        assert(regs[3]==0x4080200 && regs[4]==0 && regs[5]==0 && regs[6]==0x101);
        assert((regs[7]&63)==15 && regs[8]==hold); /* HOLD_LINES was not written. */
        int old_writes=writes;
        assert(publish(3)==0 && writes==old_writes); /* No replay on duplicate delivery. */
        assert(power_calls==1 && di_calls==1 && security_calls==1);
    }
    for(unsigned caps=0;caps<4;caps++) {
        reset();sr_info.sr_support=caps;probe();assert(publish(3)==0);
        unsigned supports_sr0=!!(caps & SUPER_CORE0_SUPPORT);
        assert(writes==(supports_sr0?9:7) && gxlx2_hw_init_status==2);
        assert(trace_reads_begin[7]==supports_sr0 && trace_reads_begin[8]==supports_sr0);
        assert(trace_writes_begin[7]==supports_sr0 && trace_writes_begin[8]==supports_sr0);
    }
    reset(); assert(publish(3)==0); probe(); assert(writes==9); /* Late module load. */
    reset(); probe(); assert(publish(1)==0 && !writes && !reads);
    assert(publish(2)==0 && !writes && !reads);
    assert(publish(3)==0 && writes==9); /* Require every bus, not just VC. */
    reset(); assert(gxlx2_video_hw_prepare()==0); gxlx2_video_hw_complete();
    assert(!gxlx2_hw_subscribed); assert(publish(3)==0 && !writes); /* Failed/incomplete probe. */
    reset(); subscribe_error=1; probe(); assert(!gxlx2_hw_subscribed && gxlx2_hw_init_status==-ENOMEM);
    assert(publish(3)==0 && !writes); /* Registration error cannot run a stray callback. */
    reset(); probe(); corrupt_readback=true; assert(publish(3)==0);
    assert(gxlx2_hw_init_status==-EIO && !gxlx2_hw_done && vpp_hold_line==8);
    corrupt_readback=false; assert(publish(3)==0 && writes==9); /* No automatic retry after error. */
    reset(); probe(); legacy_vpp=false; assert(publish(3)==0);
    assert(gxlx2_hw_init_status==-EINVAL && !writes && !reads);
    reset(); probe(); glayer_info[0].fgrain_support=true; assert(publish(3)==0);
    assert(gxlx2_hw_init_status==-EOPNOTSUPP && !writes && !reads);
    reset(); probe(); gxlx2_video_hw_cancel(); assert(publish(3)==0 && !writes);
    for (int id=0;id<64;id++) {
        if(id==0x2a)continue;
        reset(); cpu=id; gxlx2_video_hw_probe_done(); gxlx2_video_hw_complete();
        assert(!gxlx2_hw_subscribed && !gxlx2_hw_probe_ready && !writes && !reads);
    }
    reset(); gxlx2_hw_init=false; gxlx2_video_hw_probe_done(); gxlx2_video_hw_complete();
    assert(!gxlx2_hw_subscribed); /* Boot opt-out keeps original video_hw_init body. */
    reset(); gxlx2_hw_init_wait=true; probe(); assert(publish(3)==0);
    assert(!writes && !reads && gxlx2_hw_init_status==1);
    struct kernel_param kp={&gxlx2_hw_run};
    assert(gxlx2_hw_run_set("invalid",&kp)==-EINVAL);
    assert(gxlx2_hw_run_set("0",&kp)==-EINVAL);
    vd_layer[0].dispbuf=&kp; assert(gxlx2_hw_run_set("1",&kp)==-EBUSY && !writes);
    vd_layer[0].dispbuf=NULL;
    assert(gxlx2_hw_run_set("1",&kp)==0 && writes==9 && gxlx2_hw_run);
    assert(gxlx2_hw_run_set("1",&kp)==-EALREADY && writes==9);
    reset(); gxlx2_hw_init_wait=true; probe();
    assert(gxlx2_hw_run_set("1",&kp)==-EAGAIN && !writes && !gxlx2_hw_manual_release);
    assert(publish(3)==0 && !writes); /* Publication alone never releases diagnostic wait. */
    assert(gxlx2_hw_run_set("1",&kp)==0 && writes==9);
    reset(); assert(gxlx2_hw_run_set("1",&kp)==-EPERM && !writes);
    gxlx2_hw_init=false;assert(gxlx2_hw_run_set("1",&kp)==-EOPNOTSUPP);
    reset(); assert(!codec_reg_bus_ready(BUS_MAX)); assert(!codec_reg_bus_ready(UINT32_MAX));
    return 0;
}
'''
    path = root / 'test.c'
    path.write_text(c)
    subprocess.run([shutil.which('clang') or 'cc', '-std=c99', '-Wall', '-Werror',
                    str(path), '-o', str(root / 'test')], check=True)
    subprocess.run([str(root / 'test')], check=True)

print('PASS: original early video_init retained; only GXLX2 SR0 capability guard changes opt-out body')
print('PASS: fixed register writes wait for successful probe/init and complete bus publication')
print('PASS: early/late consumers, missing buses, allocation/subscription/readback errors, cancellation and duplicate events')
print('PASS: every fixed read/write has paired trace markers, including the read half of RMW')
print('PASS: diagnostic wait performs no MMIO until explicit release; rejects active frames and repeat execution')
print('Host models only: ARM build, IRQ timing, real MMIO and physical playback remain pending.')
