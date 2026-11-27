#!/usr/bin/env python3
"""Exercise the production 0038 bounded ring with host kernel stubs."""
from pathlib import Path
import subprocess
import tempfile

patch = Path(__file__).resolve().parents[1] / "patches/linux/0038-gxlx2-playback-timeline.patch"
raw = patch.read_text()
start = raw.index("+++ b/drivers/amlogic/media/common/rdma/e900_playback_trace.h")
end = raw.find("\n--- a/", start)
if end < 0:
    end = len(raw)
section = raw[start:end]
body = "\n".join(line[1:] for line in section.splitlines()
                 if line.startswith("+") and not line.startswith("+++"))
body = body.replace("#include <linux/jiffies.h>", "")
assert "e900_playback_batch_floor" in body
assert "e900_playback_samples < 16" in body
assert "e900_playback_status = 2" in body
assert "e900_playback_batch = 0" not in body
assert "E900_PLAYBACK_CAP 4096" in body
assert "E900_PLAYBACK_PAGE 8" in body
assert "e900_playback_normal_table(handle, trigger, table, count)" in raw
assert "e900_playback_normal_end(handle, status, kind)" in raw
assert "e900_osd_trace_prepare" in raw and "e900_osd_trace_irq" in raw
assert "OSD_RDMA_CHANNEL_INDEX, 0, RDMA_TABLE_INTERNAL_COUNT" in raw
assert "E900_PB_SAFE_READ" in raw and "VPP_FIFO_STATUS" in raw
assert "if (!legacy_sample && !e900_playback_sample_take())" in raw
assert "e900_playback_direct_selected(reg)" in raw
assert "e900_playback_selected(u32 reg)" in raw

prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
typedef uint32_t u32;
typedef uint64_t u64;
#define DEFINE_SPINLOCK(x) int x
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define spin_lock_irqsave(lock,flags) ((void)(lock),(void)(flags))
#define spin_unlock_irqrestore(lock,flags) ((void)(lock),(void)(flags))
#define EXPORT_SYMBOL(x)
#define module_param_cb(...)
#define module_param_named(...)
#define PAGE_SIZE 4096
#define RDMA_NUM 8
#define xchg(p,v) __extension__ ({ __typeof__(*(p)) old=*(p); *(p)=(v); old; })
#define get_jiffies_64() (++ticks)
#define scnprintf snprintf
struct kernel_param { void *arg; };
struct kernel_param_ops { int (*set)(const char *, const struct kernel_param *); int (*get)(char *, const struct kernel_param *); };
static unsigned long long ticks;
static bool cpu_ok = true;
static bool is_meson_gxlx2_cpu(void) { return cpu_ok; }
static int kstrtouint(const char *s, unsigned base, unsigned *v) {
    char *end; *v = strtoul(s, &end, base); return (*end == '\n' || *end == 0) ? 0 : -EINVAL;
}
static bool e900_playback_selected(u32 reg) {
    return (reg >= 0x1a00 && reg <= 0x1aff) ||
           (reg >= 0x1d00 && reg <= 0x1dff) ||
           (reg >= 0x3800 && reg <= 0x38ff) ||
           (reg >= 0x3d60 && reg <= 0x3d6f);
}
'''
main = r'''
int main(void) {
    char data[4096];
    u32 old, batch, next;
    unsigned i;
    assert(e900_playback_phase_set("1", NULL) == 0);
    assert(e900_playback_scan_set("1", NULL) == 0);
    assert(e900_playback_status == 1 && e900_playback_count == 1);
    assert(e900_playback_rows[0].kind == 1 && e900_playback_rows[0].phase == 1);
    e900_playback_note(1, 2, 7, 0, 0, 1, 3, 0);
    batch = e900_playback_begin(2, 1, 1, 2);
    assert(batch != 0);
    e900_playback_note(2, 4, 0, batch, 1, 0x3800, 0xd05f, 0);
    e900_playback_note(2, 4, 0, batch, 1, 0x3802, 0x55, 1);
    e900_playback_note(2, 5, 0, batch, 1, 0, 1, 2);
    assert(e900_playback_count == 6);
    assert(e900_playback_rows[2].session == 7 && e900_playback_rows[2].phase == 1);
    assert(e900_playback_scan_set("0", NULL) == 0);
    assert(e900_playback_data_get(data, NULL) > 0);
    assert(strstr(data, "3800 d05f 0") != NULL);
    old = batch;
    assert(e900_playback_phase_set("2", NULL) == 0);
    assert(e900_playback_scan_set("1", NULL) == 0);
    assert(e900_playback_rows[0].phase == 2 && e900_playback_count == 1);
    e900_playback_note(2, 4, 0, old, 1, 0x3800, 0, 0);
    assert(e900_playback_count == 1); /* stale batch never enters new generation */
    next = e900_playback_begin(3, 2, 0, 500); /* mutable OSD window */
    assert(next > old);
    e900_playback_note(3, 4, 0, next, 2, 0x1a10, 1, 1);
    e900_playback_note(3, 4, 0, next, 2, 0x1a11, 2, 1);
    assert(e900_playback_rows[1].aux == 500);
    assert(e900_playback_rows[3].aux == 1);
    {
        u32 table[] = {0x3800, 0xd05f, 0x3802, 0x55};
        e900_playback_normal_table(1, 1, table, 2);
        assert(e900_playback_normal_pending[1] != 0);
        e900_playback_normal_end(1, 0x80, 2);
        assert(e900_playback_normal_pending[1] == 0);
        assert(e900_playback_rows[e900_playback_count - 1].kind == 5);
    }
    assert(e900_playback_sample_take());
    assert(e900_playback_samples == 1);
    assert(e900_playback_scan_set("0", NULL) == 0);
    assert(!e900_playback_sample_available());
    assert(e900_playback_phase_set("3", NULL) == 0);
    assert(e900_playback_scan_set("1", NULL) == 0);
    for (i = 0; i < E900_PLAYBACK_CAP; i++)
        e900_playback_note(1, 2, 7, 0, 0, 5, i, 0);
    assert(e900_playback_status == 2 && e900_playback_overflow == 1);
    assert(e900_playback_count == E900_PLAYBACK_CAP);
    cpu_ok = false;
    assert(e900_playback_scan_set("1", NULL) == -ENODEV);
    puts("Playback timeline ring: PASS");
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix="e900-playback-test-") as d:
    source = Path(d) / "test.c"
    exe = Path(d) / "test"
    source.write_text(prefix + body + main)
    subprocess.run(["cc", "-std=gnu99", "-Wall", "-Wextra", "-Wno-unused-parameter",
                    "-Wno-unused-variable", "-o", str(exe), str(source)], check=True)
    subprocess.run([str(exe)], check=True)
print("0038 source hooks: PASS")
