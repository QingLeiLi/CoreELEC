#!/usr/bin/env python3
"""Host tests of real diagnostic C fragments and paired-evidence semantics."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

P = Path(__file__).resolve().parents[1]
A = Path(os.environ.get('E900_AUDIT_ROOT', P.parent / 'coreelec-audit'))
spec = importlib.util.spec_from_file_location('e900_debug', P / 'scripts/e900-debug.py')
debug = importlib.util.module_from_spec(spec); spec.loader.exec_module(debug)


def function(source, name):
    m = re.search(r'^(?:static )?(?:int|void) ' + name + r'\([^;]*?\)\s*\{', source, re.M)
    assert m, name
    start = source.index('{', m.start()); end = start + 1; depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}'); end += 1
    return source[m.start():end]


with tempfile.TemporaryDirectory(prefix='e900-debug-check-') as temp:
    t = Path(temp)
    for row in json.loads((P / 'tests/source-fixtures.json').read_text()):
        if row['repo'] != 'CoreELEC/linux-amlogic': continue
        dst = t / row['path']; dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(A / 'sources' / row['path'].replace('/', '__'), dst)
    for patch in sorted((P / 'patches/linux').glob('*.patch')):
        subprocess.run(['git', 'apply', str(patch)], cwd=t, check=True)
    header = (t / 'include/linux/amlogic/media/registers/e900_debug.h').read_text()
    macro = '\n'.join(line for line in header.splitlines() if not line.startswith('#include'))
    hw = (t / 'drivers/amlogic/media/video_sink/video_hw.c').read_text()
    output = function(hw, 'e900_debug_output')
    assert 'WRITE_' not in output and 'WR_MPEG' not in output
    assert 'canvas_read(' in output and 'canvas_read_hw' not in output
    assert hw.count('e900_debug_output(blend_requested);') == 1
    # The existing suite executes all active-frame/bank/bus guard paths; the
    # new snapshot call must remain below these exact guards and not elsewhere.
    old_hook = hw[hw.index('static void e900_stage_output'):hw.index('E900_DEBUG_CHANNEL("video")')]
    assert old_hook.index('mif->vd_if0_gen_reg != 0x1a50') < old_hook.index('e900_debug_output(')
    c = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <errno.h>
typedef uint32_t u32;
#define noinline __attribute__((noinline))
#define READ_ONCE(x) (x)
#define IS_ENABLED(x) E900_TEST_ENABLED
#define IS_REACHABLE(x) E900_TEST_ENABLED
#define WRITE_ONCE(x,v) ((x)=(v))
#define ATOMIC_INIT(x) {x}
typedef struct {int v;} atomic_t;
static int atomic_inc_return(atomic_t *x){return ++x->v;}
static unsigned cpu=0x2a,lines,reads;
static bool is_meson_gxlx2_cpu(void){return cpu==0x2a;}
struct kernel_param {void *arg;};
struct kernel_param_ops {int (*set)(const char*,const struct kernel_param*); int (*get)(char*,const struct kernel_param*);};
static int param_get_uint(char *b,const struct kernel_param *p){return sprintf(b,"%u",*(unsigned*)p->arg);}
static int kstrtouint(const char*s,unsigned base,unsigned*out){char*e;unsigned long n;if(*s=='-')return -EINVAL;n=strtoul(s,&e,base);if(e==s||*e||n>UINT32_MAX)return -EINVAL;*out=n;return 0;}
static unsigned cmpxchg(unsigned*p,unsigned old,unsigned n){unsigned seen=*p;if(seen==old)*p=n;return seen;}
#define module_param_cb(...)
#define MODULE_PARM_DESC(...)
static void logmsg(const char*fmt,...) __attribute__((format(printf,1,2)));
static void logmsg(const char*fmt,...){char b[2048];va_list a;va_start(a,fmt);vsnprintf(b,sizeof b,fmt,a);va_end(a);lines++;}
#define pr_info(...) logmsg(__VA_ARGS__)
struct mif {unsigned vd_if0_gen_reg3,vd_if0_canvas0,vd_if0_canvas1,vd_if0_luma_x1,vd_if0_luma_y1,vd_if0_chroma_x0,vd_if0_chroma_y0,vd_if0_rpt_loop,viu_vd_fmt_w;};
#define hw_vd_reg_s mif
struct vframe_s {unsigned index,pts,flag,plane_num,width,height,type,bitdepth;};
struct video_layer_s {struct mif vd_mif_reg;unsigned enabled,enabled_status_saved,onoff_state,disable_video,global_output,force_black,property_changed,new_frame,new_vpp_setting,bypass_pps,cur_canvas_id;bool switch_vf,vd1_vd2_mux;struct vframe_s *dispbuf,*vf_ext;};
struct canvas_s {unsigned long addr;unsigned width,height,wrap,blkmode;};
static struct video_layer_s vd_layer[1];static unsigned e900_stage_epoch;
static void canvas_read(unsigned id,struct canvas_s*c){assert(id<=255);c->width=1280;c->height=720;}
static unsigned live(unsigned r){reads++;return r;}
#define READ_VCBUS_REG(r) live(r)
#define VSYNC_RD_MPEG_REG(r) live(r)
#define VIU_MISC_CTRL0 0x1a06
#define VIU_MISC_CTRL1 0x1a07
#define VPP_HOLD_LINES 0x1d22
#define VPP_OFIFO_SIZE 0x1d27
#define VIU_OSD1_CTRL_STAT 0x1a10
#define AFBC_ENABLE 0x1ae0
#define VPP_CLIP_MISC0 0x1dd9
#define VPP_CLIP_MISC1 0x1dda
#define VPP_VADJ_CTRL 0x1d40
'''
    rd = (t / 'drivers/amlogic/media/common/rdma/rdma.c').read_text()
    mgr = (t / 'drivers/amlogic/media/common/rdma/rdma_mgr.c').read_text()
    getters = function(rd, 'e900_rdma_state_get') + function(mgr, 'e900_manager_state_get')
    assert 'READ_VCBUS' not in getters and 'WRITE_' not in getters
    c += r'''
#define RDMA_NUM 2
#define PAGE_SIZE 4096
#define scnprintf snprintf
static int vsync_rdma_handle[2],enable[2],cur_enable[2],pre_enable_[2],irq_count[2],vsync_cfg_count[2];
static bool first_config[2],rdma_done[2];static u32 force_rdma_config[2];
struct rdma_instance_s {unsigned used,keep_buf;int rdma_item_count,rdma_write_count,rdma_table_size,not_process,prev_trigger_type;};
static struct {struct rdma_instance_s rdma_ins[2];} rdma_info;
''' + getters
    experiment=function(hw, 'e900_gen3_experiment')
    assert hw.count('e900_gen3_experiment(layer, vd_mif_reg, bit_mode);')==1
    assert 'READ_VCBUS' not in experiment
    experiment_prelude=r'''
static bool legacy_vpp=true,gxlx2_gen3_clear_high;
static unsigned gxlx2_gen3_clear_high_submits;
static unsigned bit_writes;
static void fixed_bits(unsigned reg,unsigned value,unsigned start,unsigned count){assert(reg==0x1aa7&&value==0&&start==12&&count==2);bit_writes++;}
#define VSYNC_WR_MPEG_REG_BITS(r,v,s,n) fixed_bits(r,v,s,n)
'''
    reachable = r'''
#if E900_TEST_ENABLED
static unsigned reachable_calls;
void e900_rdma_progress(u32 v[4]){for(unsigned i=0;i<4;i++)v[i]=0;}
void e900_csc_progress(u32 v[9]){for(unsigned i=0;i<9;i++)v[i]=0;}
void e900_hdr_recovery_edge(bool old_output,bool new_output,bool active_frame,u32 session,int mode){(void)old_output;(void)new_output;(void)active_frame;(void)session;(void)mode;reachable_calls++;}
void e900_hdr_recovery_cancel(void){reachable_calls++;}
void e900_playback_note(u32 source,u32 kind,u32 session,u32 batch,u32 handle,u32 reg,u32 value,u32 aux){(void)source;(void)kind;(void)session;(void)batch;(void)handle;(void)reg;(void)value;(void)aux;reachable_calls++;}
u32 e900_playback_begin(u32 source,u32 handle,u32 trigger,u32 total){(void)source;(void)handle;(void)trigger;(void)total;reachable_calls++;return 0;}
bool e900_playback_active(void){reachable_calls++;return false;}
bool e900_playback_batch_valid(u32 batch){(void)batch;reachable_calls++;return false;}
bool e900_playback_sample_available(void){reachable_calls++;return false;}
bool e900_playback_sample_take(void){reachable_calls++;return false;}
#endif
'''
    c += macro + reachable + '\nE900_DEBUG_CHANNEL("test")\n' + output + experiment_prelude + experiment + r'''
int main(void){struct kernel_param p={&gxlx2_debug_events};struct vframe_s vf={0};
 assert(!e900_playback_direct_selected(0));
 e900_hdr_recovery_edge(true,false,true,1,2);e900_hdr_recovery_cancel();
 e900_playback_note(1,2,3,4,5,6,7,8);assert(!e900_playback_begin(1,2,3,4));
 assert(!e900_playback_active()&&!e900_playback_batch_valid(1));
 assert(!e900_playback_sample_available()&&!e900_playback_sample_take());
#if E900_TEST_ENABLED
 assert(reachable_calls==8);
#endif
 e900_debug_event("off",0,0,0,0);assert(lines==0);
 assert(e900_debug_ops.set("513",&p)==-ERANGE);assert(gxlx2_debug_events==0);
 assert(e900_debug_ops.set("-1",&p)<0);assert(gxlx2_debug_events==0);
 assert(!e900_debug_ops.set("2",&p));cpu=0x21;e900_debug_event("other",0,0,0,0);assert(lines==0&&gxlx2_debug_events==2);
 cpu=0x2a;e900_debug_event("one",0,0,0,0);e900_debug_event("two",0,0,0,0);e900_debug_event("exhausted",0,0,0,0);assert(lines==2&&gxlx2_debug_events==0);
 assert(!e900_debug_ops.set("0",&p));assert(!e900_debug_ops.set("512",&p));
 u32 csc_progress[9]={1,2,3,4,5,6,7,8,9};e900_csc_progress(csc_progress);for(unsigned i=0;i<9;i++)assert(!csc_progress[i]);
 u32 progress[4]={1,2,3,4};e900_rdma_progress(progress);assert(!progress[0]&&!progress[1]&&!progress[2]&&!progress[3]);
 char out[4096];irq_count[0]=123;rdma_info.rdma_ins[1].rdma_item_count=77;
 assert(e900_rdma_state_get(out,&p)>0);assert(strstr(out,"irq=123"));
 assert(e900_manager_state_get(out,&p)>0);assert(strstr(out,"items=77"));
 vd_layer[0].dispbuf=&vf;e900_debug_output(0);assert(reads==19);assert(lines==10);
 for(unsigned flags=0;flags<32;flags++){
  cpu=(flags&1)?0x2a:0x21;legacy_vpp=!!(flags&2);gxlx2_gen3_clear_high=!!(flags&4);vd_layer[0].vd1_vd2_mux=!!(flags&8);vd_layer[0].vd_mif_reg.vd_if0_gen_reg3=(flags&16)?0x1aa7:0x3216;
  unsigned before=bit_writes;e900_gen3_experiment(&vd_layer[0],&vd_layer[0].vd_mif_reg,0);
  assert(bit_writes-before==(unsigned)((flags&23)==23&&!(flags&8)));
 }
 return 0;}
'''
    src = t / 'test.c'; src.write_text(c)
    for enabled in (0, 1):
        subprocess.run([shutil.which('clang') or 'cc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-DE900_TEST_ENABLED='+str(enabled), str(src), '-o', str(t/'test')],check=True)
        subprocess.run([str(t/'test')],check=True)
        print(f'PASS: strict host compilation and execution, configuration enabled={enabled}')
    # Compare should retain new/missing fields and never classify absent data
    # or a rejected capture as a black pixel image.
    def doc(value, capture):
        return dict(label=value, before={'boot_id': {'text': 'boot'}}, after={'parameters': {}},
                    observations=debug.parse_logs('e900-snapshot kind=route viu_misc0='+value),pixel_capture=capture)
    left,right=t/'normal',t/'abnormal';left.mkdir();right.mkdir()
    (left/'snapshot.json').write_text(json.dumps(doc('0',{'status':'ok','sha256':'abc'})))
    (right/'snapshot.json').write_text(json.dumps(doc('1',{'status':'failed','error':'timeout'})))
    result=debug.compare(left,right)
    assert result['same_boot'] and result['configuration_differences']
    assert 'same_hash' not in result['pixel_comparison']
    missing=doc('1',{'status':'skipped'});missing['observations']=[]
    (right/'snapshot.json').write_text(json.dumps(missing))
    assert debug.compare(left,right)['missing_interval_evidence']==['right']
    png=debug.png_bgr(bytes([255,0,0]*4),2,2);assert png.startswith(b'\x89PNG\r\n\x1a\n')
print('PASS: full patch application; real default-off/bounded CPU-scoped C event channel and fixed snapshot fragment compile and execute')
print('PASS: paired comparisons preserve missing/failed evidence and do not infer downstream pixels or a root cause')
print('ARM build, full driver linking, hardware timing and pixel calibration remain pending.')
# Exercise the real ioctl consumer against the pinned public completion enum,
# not a private guessed hexadecimal constant.
from unittest import mock
header_path='include/linux/amlogic/media/video_sink/amvideocap.h'
public=(A/'sources'/header_path.replace('/','__')).read_text()
finished=int(re.search(r'AMVIDEOCAP_STATE_FINISHED_CAPTURE\s*=\s*(\d+)',public)[1])
assert debug.CAPTURE_FINISHED==finished
with tempfile.TemporaryDirectory(prefix='e900-canvas-api-') as temporary:
    root=Path(temporary)
    for state_value,expected in [(finished,'ok'),(200,'failed')]:
        dest=root/str(state_value);dest.mkdir()
        def ioctl(fd,command,arg,*rest):
            if command & 0x80000000:
                value={0x11:320,0x12:180,0x31:state_value,0x21:1280,0x22:720,0x13:42,0x10:0x1000200}[command&255]
                arg[:4]=value.to_bytes(4,'little')
            return 0
        with mock.patch.object(debug,'read',return_value={'status':'ok','text':'ammvdec_h264'}), \
             mock.patch.object(debug.os,'open',return_value=7), \
             mock.patch.object(debug.os,'read',return_value=bytes([0,0,255])*320*180), \
             mock.patch.object(debug.os,'close'), \
             mock.patch.object(debug.fcntl,'ioctl',side_effect=ioctl), \
             mock.patch.object(debug.time,'sleep'):
            result=debug.canvas_capture(dest)
        assert result['status']==expected,result
        assert (dest/'canvas.png').exists()==(expected=='ok')
print('PASS: actual ioctl consumer accepts pinned decimal completion enum and rejects in-progress frames')
