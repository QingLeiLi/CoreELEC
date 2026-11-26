#!/usr/bin/env python3
"""Compile the 0037 production edge/consume state machine with host stubs."""
from pathlib import Path
import subprocess
import tempfile

PATCH = Path(__file__).resolve().parents[1] / "patches/linux/0037-gxlx2-force-hdr2-reconfig-on-global-output-recovery.patch"
raw = PATCH.read_text()
start = raw.index("+static struct vframe_s fake_vframe;")
end = raw.index("\n static bool video_on[VD_PATH_MAX];", start)
production = "\n".join(line[1:] for line in raw[start:end].splitlines() if line.startswith("+"))
assert "static bool e900_hdr_recovery_consume" in production
assert "e900_hdr_recovery_edge" in production
assert "e900_hdr_recovery_cancel" in production
assert "vf != &fake_vframe" in production
assert "time_after_eq" in production
assert "SIG_FORCE_CHG" in raw and "e900_hdr_force = e900_hdr_recovery_consume" in raw
assert "video_post_process(" in raw and "e900_hdr_post_calls++" in raw
assert "old_output == 0 || old_output == 1" in raw
assert "active_frame && (!old_output || vd_layer[0].enabled)" in raw
assert "vd_layer[0].dispbuf" in raw
assert "vd_layer[0].global_output == 1" in raw
assert "!on && (layer_id == 0 || layer_id == 0xff)" in raw
assert "VD1_HDR2_CTRL) & 0x1000" not in raw

prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;
typedef int atomic_t;
#define ATOMIC_INIT(x) (x)
#define DEFINE_SPINLOCK(x) int x
#define READ_ONCE(x) (x)
#define spin_lock_irqsave(lock, flags) ((void)(lock), (void)(flags))
#define spin_unlock_irqrestore(lock, flags) ((void)(lock), (void)(flags))
#define atomic_inc_return(p) (++*(p))
#define EXPORT_SYMBOL(x)
#define module_param_cb(...)
#define MODULE_PARM_DESC(...)
#define module_param_named(...)
#define pr_info(...) ((void)0)
#define VMODE_NULL 0
#define VMODE_INVALID -1
#define VD1_PATH 0
#define HZ 100
#define time_before(a,b) ((long)((a)-(b)) < 0)
#define time_after_eq(a,b) ((long)((a)-(b)) >= 0)
struct vframe_s { int marker; };
struct vinfo_s { int mode; };
enum vd_path_e { VD1 = VD1_PATH, VD2 = 1 };
struct kernel_param { void *arg; };
struct kernel_param_ops { int (*set)(const char *, const struct kernel_param *); int (*get)(char *, const struct kernel_param *); };
static unsigned long jiffies;
static bool cpu_ok = true, layer_on = true, dolby_on;
static u32 video_session = 1;
static bool is_meson_gxlx2_cpu(void) { return cpu_ok; }
static bool get_video_enabled(void) { return layer_on; }
static bool is_dolby_vision_on(void) { return dolby_on; }
static u32 e900_hdr_recovery_video_session(void) { return video_session; }
static int param_set_bool(const char *s, const struct kernel_param *p) {
    *(bool *)p->arg = s[0] == '1'; return 0;
}
static int param_get_bool(char *s, const struct kernel_param *p) {
    (void)s; (void)p; return 0;
}
'''
main = r'''
int main(void) {
    struct vframe_s real = {1};
    struct vinfo_s mode = {3}, changed = {4};
    struct kernel_param param = {&gxlx2_hdr_recovery};
    assert(!e900_hdr_recovery_consume(&real, &mode, VD1));
    e900_hdr_recovery_edge(true, false, true, 1, 3); /* default off */
    e900_hdr_recovery_edge(false, true, true, 1, 3);
    assert(e900_hdr_requests == 0);
    assert(e900_hdr_enable_set("1", &param) == 0);
    assert(!e900_hdr_recovery_consume(&real, &mode, VD1)); /* first play */
    e900_hdr_recovery_edge(true, false, false, 1, 3); /* no frame at off */
    e900_hdr_recovery_edge(false, true, true, 1, 3);
    assert(e900_hdr_requests == 0);
    e900_hdr_recovery_edge(true, false, true, 1, 3);
    layer_on = false; /* global 0 makes get_video_enabled false */
    e900_hdr_recovery_edge(false, true, true, 1, 3);
    assert(e900_hdr_requests == 1);
    assert(!e900_hdr_recovery_consume(&real, &mode, VD2));
    assert(!e900_hdr_recovery_consume(&fake_vframe, &mode, VD1));
    layer_on = false;
    assert(!e900_hdr_recovery_consume(&real, &mode, VD1));
    layer_on = true;
    assert(e900_hdr_recovery_consume(&real, &mode, VD1));
    assert(!e900_hdr_recovery_consume(&real, &mode, VD1)); /* one shot */
    e900_hdr_recovery_edge(true, false, true, 1, 3);
    e900_hdr_recovery_cancel(); /* Stop */
    e900_hdr_recovery_edge(false, true, true, 1, 3);
    assert(e900_hdr_requests == 1);
    e900_hdr_recovery_edge(true, false, true, 1, 3);
    e900_hdr_recovery_edge(false, true, true, 2, 3); /* new provider */
    assert(e900_hdr_requests == 1);
    e900_hdr_recovery_edge(true, false, true, 1, 3);
    e900_hdr_recovery_edge(false, true, true, 1, 4); /* mode changed */
    assert(e900_hdr_requests == 1);
    e900_hdr_recovery_edge(true, false, true, 1, 3);
    jiffies += 500;
    e900_hdr_recovery_edge(false, true, true, 1, 3); /* expired */
    assert(e900_hdr_requests == 1);
    e900_hdr_recovery_edge(true, false, true, 1, 3);
    e900_hdr_recovery_edge(false, true, true, 1, 3);
    video_session = 2;
    assert(!e900_hdr_recovery_consume(&real, &mode, VD1));
    assert(e900_hdr_consumed == 1);
    cpu_ok = false;
    e900_hdr_recovery_edge(true, false, true, 2, 3);
    e900_hdr_recovery_edge(false, true, true, 2, 3);
    assert(e900_hdr_requests == 2);
    assert(!e900_hdr_recovery_consume(&real, &mode, VD1));
    cpu_ok = true;
    e900_hdr_recovery_edge(true, false, true, 2, 3);
    e900_hdr_recovery_edge(false, true, true, 2, 3);
    dolby_on = true;
    assert(!e900_hdr_recovery_consume(&real, &mode, VD1));
    dolby_on = false;
    assert(e900_hdr_recovery_consume(&real, &mode, VD1));
    assert(!e900_hdr_recovery_consume(&real, &changed, VD1));
    assert(e900_hdr_consumed == 2);
    assert(e900_hdr_enable_set("0", &param) == 0);
    assert(!e900_hdr_recovery_consume(&real, &mode, VD1));
    puts("HDR recovery state machine: PASS");
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix="e900-hdr-test-") as d:
    source = Path(d) / "test.c"
    exe = Path(d) / "test"
    source.write_text(prefix + production + main)
    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Wno-unused-parameter", "-Wno-unused-variable", "-o", str(exe), str(source)], check=True)
    subprocess.run([str(exe)], check=True)
