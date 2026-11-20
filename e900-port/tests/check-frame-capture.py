#!/usr/bin/env python3
"""Run the real capture fragment and GE2D queue/command code with kernel stubs."""
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
FILES = [
    'drivers/amlogic/media/video_sink/amvideocap.c',
    'drivers/amlogic/media/common/ge2d/stretchblt.c',
    'drivers/amlogic/media/common/ge2d/ge2d_wq.c',
]


def function(source, name):
    match = re.search(r'^(?:static )?(?:int|void) ' + name + r'\([^;]*?\)\s*\{',
                      source, re.M)
    if not match:
        raise AssertionError('Missing function: ' + name)
    start = source.index('{', match.start())
    depth, end = 1, start + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end] + '\n'


with tempfile.TemporaryDirectory(prefix='e900-capture-lifetime-') as directory:
    root = Path(directory)
    manifest = {r['path']: r for r in json.loads((PORT / 'tests/source-fixtures.json').read_text())}
    for path in FILES:
        data = (AUDIT / 'sources' / path.replace('/', '__')).read_bytes()
        if hashlib.sha256(data).hexdigest() != manifest[path]['sha256']:
            raise AssertionError('Source fixture mismatch: ' + path)
        dest = root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    subprocess.run(['git', 'apply', str(PORT / 'patches/linux/0011-gxlx2-synchronous-frame-capture.patch')],
                   cwd=root, check=True)
    capture = (root / FILES[0]).read_text()
    stretch = (root / FILES[1]).read_text()
    queue = (root / FILES[2]).read_text()
    start = capture.index('\tif (is_meson_gxlx2_cpu())', capture.index('ge2d_context_config_ex('))
    end = capture.index('canvas_pool_map_free_canvas(canvas_idx);', start)
    end += len('canvas_pool_map_free_canvas(canvas_idx);')
    fragment = capture[start:end]
    command = function(stretch, '_stretchblt_noalpha')
    fields = sorted(set(re.findall(r'ge2d_cmd_cfg->(\w+)', command)))
    harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <string.h>
#define UPDATE_DP_GEN 1
#define OPERATION_LOGIC 1
#define LOGIC_OPERATION_COPY 2
#define LOGIC_OPERATION_SET 3
#define IS_STRETCHBLIT 4
#define ge2d_log_dbg(...) ((void)0)
#define spin_lock(x) ((void)(x))
#define spin_unlock(x) ((void)(x))
#define IS_ERR(x) false
#define list_entry(ptr, type, member) ((type *)(ptr))
struct head { void *next; };
struct completion { int done; };
struct ge2d_dp_gen_s { int alu_const_color; };
struct ge2d_config_s { int update_flag; };
struct ge2d_cmd_s { int ''' + ', '.join(fields) + r'''; };
struct ge2d_context_s {
    struct ge2d_cmd_s cmd;
    struct ge2d_dp_gen_s dp;
    struct ge2d_config_s config;
    struct head free_queue, work_queue;
    int lock, cmd_complete;
};
struct ge2d_queue_item_s {
    struct ge2d_cmd_s cmd;
    struct ge2d_config_s config;
    struct head list;
};
static struct { struct { struct completion cmd_in_com; } event; } ge2d_manager;
static struct ge2d_queue_item_s job;
static struct ge2d_cmd_s submitted;
static int cpu, completions;
static bool pending, canvas_live, released_before_done;
static bool is_meson_gxlx2_cpu(void) { return cpu == 0x2a; }
static bool work_queue_no_space(struct ge2d_context_s *w) { (void)w; return false; }
static void complete(struct completion *c) { c->done++; }
static void list_move_tail(struct head *item, struct head *queue) {
    (void)item; (void)queue; pending = true; submitted = job.cmd;
}
static void finish_worker(void) {
    assert(pending && canvas_live);
    completions++; pending = false; job.cmd.wait_done_flag = 0;
}
#define wait_event_interruptible(queue, condition) do { \
    (void)(queue); finish_worker(); assert(condition); \
} while (0)
static struct ge2d_cmd_s *ge2d_wq_get_cmd(struct ge2d_context_s *w) { return &w->cmd; }
static struct ge2d_dp_gen_s *ge2d_wq_get_dp_gen(struct ge2d_context_s *w) { return &w->dp; }
static void canvas_pool_map_free_canvas(int index) {
    assert(index == 3 && canvas_live);
    released_before_done = pending; canvas_live = false;
}
''' + function(queue, 'ge2d_wq_add_work') + command
    harness += function(stretch, 'stretchblt_noalpha')
    harness += function(stretch, 'stretchblt_noalpha_noblk')
    harness += r'''
static void capture_fragment(struct ge2d_context_s *ctx, int sw, int sh, int dw, int dh) {
    struct ge2d_context_s *ge2d_amvideocap_context = ctx;
    struct { struct { int width, height; } src_para, dst_para; } ge2d_config;
    int canvas_idx = 3;
    ge2d_config.src_para.width = sw; ge2d_config.src_para.height = sh;
    ge2d_config.dst_para.width = dw; ge2d_config.dst_para.height = dh;
''' + fragment + r'''
}
int main(void) {
    int sizes[][4] = {{1280,720,320,180}, {1280,720,640,360},
                     {1280,720,1280,720}, {1920,1080,320,180}};
    for (cpu = 0; cpu < 0x40; cpu++) {
        for (unsigned n = 0; n < sizeof(sizes)/sizeof(sizes[0]); n++) {
            struct ge2d_context_s context;
            memset(&context, 0, sizeof(context));
            memset(&job, 0, sizeof(job));
            memset(&ge2d_manager, 0, sizeof(ge2d_manager));
            context.free_queue.next = &job;
            pending = released_before_done = false;
            canvas_live = true; completions = 0;
            capture_fragment(&context, sizes[n][0], sizes[n][1], sizes[n][2], sizes[n][3]);
            assert(submitted.src1_x_start == 0 && submitted.src1_y_start == 0);
            assert(submitted.src1_x_end == sizes[n][0]-1);
            assert(submitted.src1_y_end == sizes[n][1]-1);
            assert(submitted.dst_x_start == 0 && submitted.dst_y_start == 0);
            assert(submitted.dst_x_end == sizes[n][2]-1);
            assert(submitted.dst_y_end == sizes[n][3]-1);
            if (cpu == 0x2a) {
                assert(submitted.wait_done_flag == 1 && completions == 1);
                assert(!pending && !released_before_done);
            } else {
                assert(submitted.wait_done_flag == 0 && completions == 0);
                assert(pending && released_before_done); /* Preserve upstream policy. */
            }
            assert(!canvas_live);
        }
    }
    return 0;
}
'''
    c = root / 'capture.c'
    c.write_text(harness)
    compiler = shutil.which('clang') or 'cc'
    for advanced in (False, True):
        flags = ['-DCONFIG_GE2D_ADV_NUM'] if advanced else []
        exe = root / ('capture-' + str(int(advanced)))
        subprocess.run([compiler, '-std=c99', '-Wall', '-Werror', *flags,
                        str(c), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)

print('PASS: actual capture/GE2D queue code completes GXLX2 work before Canvas release')
print('PASS: coordinates, all CPU IDs and both scaler build options preserve other SoC policy')
print('Host queue model only: real DMA, interrupted waits, full ARM build and patched-driver hardware remain pending.')
